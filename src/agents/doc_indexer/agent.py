"""O INDEXADOR — PDF → `DocumentoIndexado` serializado. **Não é agente.**

ONDA 2 do desenho do Agente Investigador (DESENHO-INVESTIGADOR-2026-08-13, §1.4
e §8.7). Mora em `src/agents/` pela topologia do repo, mas a LIÇÃO 5 é explícita
e vale como contrato: *"o pré-processamento é código determinístico + no máximo
1 chamada de OCR; não é agente"*. Não há loop, não há decisão de ferramenta, não
há prompt que julgue nada. Há um pipeline de sete passos, dos quais exatamente
um fala com um modelo — e só quando o gate determinístico acusa.

    0. bytes (GCS ou base64) → doc_hash = sha256(bytes)   [confere o congelado]
    1. PyMuPDF: texto nativo por página + spans com bbox
    2. GATE por página (ocr_gate da casa, SEM LLM)        → páginas inalcançáveis
    3. [ÚNICA CHAMADA LLM] só as inalcançáveis vão ao Gemini (vision.py)
    4. costura: {pagina: texto}, na ordem, método por página
    5. segmentação determinística (garantis_shared.segmentacao)
    6. bbox por sentença + extractor_version por página
    7. DocumentoIndexado

## O que este módulo garante, e o que ele deliberadamente não faz

**Garante determinismo do texto.** Mesmo PDF, mesmo gate, sem OCR ⇒ o mesmo
`DocumentoIndexado`, byte por byte, para sempre — porque tudo entre o passo 1 e
o 7 é código puro (a segmentação do shared é travada por teste de AST). É o que
o `test_determinismo` prende. Com OCR a garantia é a do §7: vem do **cache**,
não do modelo, e a chave é `(doc_hash, extractor_version)`.

**Não cacheia.** O cache do `DocumentoIndexado` é a onda 3 (`journal.py`, que
ainda não está na wheel consumida aqui). A rota já devolve `cache_hit: false`
para que o contrato de wire não mude quando a camada entrar — mudar o shape do
envelope depois é o que quebra o consumidor.

## O `metodo` de um documento MISTO, e por que ele importa por PÁGINA

`DocumentoIndexado.metodo` é do documento inteiro (`native` | `ocr_gemini` |
`misto`), e `misto` sozinho não diz ao humano se a citação da folha 12 é contra
o PDF ou contra o OCR. Por isso a `extractor_version` da **página** carrega o
método, e é ela que a `Ancora` daquela sentença herda: uma folha nativa num
documento misto continua tendo citação contra o PDF real, e dizer o contrário
enfraqueceria uma evidência que é forte.

O `DocumentoIndexado` tem uma `extractor_version` só (é a chave de cache do
documento). Para misto ela declara os DOIS métodos — `"misto[pymupdf-1.28.2|
ocr-gemini-3.1-flash-lite]+norm-2"` — em vez de escolher um: escolher faria a
metade não-escolhida mentir, e o mapa página→método fica no `gate_ocr`, que é
onde a auditoria olha.
"""
from __future__ import annotations

import base64
import logging
from typing import Any, Optional

from .._utils.feature_flags import flag_enabled
from . import extracao, gate
from .ocr import ocr_paginas
from .schemas import IndexarRequest, IndexarResponse

logger = logging.getLogger(__name__)

__all__ = ["FLAG_DOC_INDEXER", "indexar", "montar_documento_indexado"]

#: `FICHAS_DOC_INDEXER_ENABLED` (§8.5). Estilo da casa: **ship inerte + flip
#: explícito**. Com a flag OFF a rota responde `success=false` sem tocar em GCS
#: nem em modelo — o PR entra com comportamento byte-idêntico ao de hoje.
FLAG_DOC_INDEXER = "FICHAS_DOC_INDEXER_ENABLED"

#: Teto de páginas que podem ir ao OCR num documento. Um PDF inteiramente
#: escaneado de 300 folhas é onde o custo explode sem aviso, e o desenho é
#: explícito em que estouro vira lacuna DECLARADA, nunca número apressado
#: (§8.6). O corte aparece em `gate_ocr.truncado`.
MAX_PAGINAS_OCR_POR_DOC = 30

#: Motivos de falha — enum FECHADO, mesma doutrina de `Rejeicao.codigo` e de
#: `Ancora.valida_contra`: o QA agrega por eles, e prosa não vira métrica.
ERRO_FLAG_OFF = "doc_indexer_desligado"
ERRO_SEM_FONTE = "sem_gcs_path_nem_pdf_base64"
ERRO_BASE64 = "pdf_base64_invalido"
ERRO_DOWNLOAD = "download_do_gcs_falhou"
ERRO_PDF_ILEGIVEL = "pdf_ilegivel"
ERRO_HASH = "documento_mudou_apos_congelamento"
ERRO_VAZIO = "documento_sem_texto"


async def indexar(
    request: IndexarRequest | dict,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> IndexarResponse:
    """PDF → `DocumentoIndexado` serializado. Nunca levanta.

    Toda falha vira `success=false` + `error` tipado, com o custo já gasto
    propagado — o step S2b decide o que fazer (fila humana, retry, seguir sem
    aquele documento). É o mesmo contrato do calculador: erro barato não
    atravessa a rede de novo como exceção.
    """
    if isinstance(request, dict):
        request = IndexarRequest(**request)

    if not flag_enabled(FLAG_DOC_INDEXER):
        return IndexarResponse(success=False, error=ERRO_FLAG_OFF)

    pdf_bytes, erro = await _obter_bytes(request)
    if erro is not None:
        return IndexarResponse(success=False, error=erro)
    assert pdf_bytes is not None

    doc_hash = extracao.doc_hash_de(pdf_bytes)
    if request.doc_hash and request.doc_hash != doc_hash:
        # §1.6: o que congela no /start é o HASH. Se o blob mudou entre lá e
        # aqui, falhar é a resposta certa — indexar o novo silenciosamente
        # produziria âncoras contra um documento que o dossiê não viu.
        logger.warning(
            "[doc_indexer] %s: hash divergente (congelado=%s, atual=%s)",
            request.doc_id, request.doc_hash[:12], doc_hash[:12],
        )
        return IndexarResponse(success=False, error=ERRO_HASH)

    doc = extracao.abrir_pdf(pdf_bytes)
    if doc is None:
        return IndexarResponse(success=False, error=ERRO_PDF_ILEGIVEL)

    # ── 1. texto nativo + spans ────────────────────────────────────────────
    textos = extracao.texto_nativo_por_pagina(doc)
    spans = extracao.spans_por_pagina(doc)
    n_paginas = len(textos)

    # ── 2. gate por página (SEM LLM) ───────────────────────────────────────
    inalcancaveis = gate.paginas_inalcancaveis(
        doc, textos, teto_paginas=MAX_PAGINAS_OCR_POR_DOC
    )
    truncado = False
    try:
        # `paginas_inalcancaveis` já corta no teto; recontar aqui só para
        # declarar o corte na telemetria, sem repetir o julgamento caro.
        truncado = len(gate.paginas_inalcancaveis(doc, textos)) > len(inalcancaveis)
    except Exception:  # pragma: no cover — telemetria nunca derruba o pipeline
        truncado = False

    # ── 3. a ÚNICA chamada de LLM ──────────────────────────────────────────
    textos_ocr: dict[int, str] = {}
    tele_ocr: dict[str, Any] = {"model": None, "cost_usd": 0.0}
    if inalcancaveis:
        llm = _provider(provider)
        if llm is None:
            logger.warning(
                "[doc_indexer] %s: %d páginas inalcançáveis mas provider indisponível "
                "— documento sai nativo com a lacuna declarada",
                request.doc_id, len(inalcancaveis),
            )
        else:
            textos_ocr, tele_ocr = await ocr_paginas(
                llm, pdf_bytes, sorted(inalcancaveis), model=model or request.model,
            )

    # ── 4-7. costura, segmentação, bbox, montagem ──────────────────────────
    indexado, erro = montar_documento_indexado(
        doc_id=request.doc_id,
        doc_hash=doc_hash,
        n_paginas=n_paginas,
        textos_nativos=textos,
        textos_ocr=textos_ocr,
        spans=spans,
        gate_ocr=gate.resumo_gate(n_paginas, inalcancaveis, truncado=truncado),
        modelo_ocr=tele_ocr.get("model"),
    )
    if erro is not None:
        return IndexarResponse(
            success=False, error=erro,
            custo=float(tele_ocr.get("cost_usd") or 0.0),
            cost_usd=float(tele_ocr.get("cost_usd") or 0.0),
            model=tele_ocr.get("model"),
        )
    assert indexado is not None

    custo = float(tele_ocr.get("cost_usd") or 0.0)
    payload = indexado.to_dict()
    payload["gate_ocr"] = {**payload.get("gate_ocr", {}), "ocr": tele_ocr}
    return IndexarResponse(
        success=True,
        documento_indexado=payload,
        metodo=indexado.metodo,
        gate_ocr=payload["gate_ocr"],
        paginas_ocr=sorted(textos_ocr),
        cache_hit=False,
        custo=custo,
        cost_usd=custo,
        model=tele_ocr.get("model"),
    )


def montar_documento_indexado(
    *,
    doc_id: str,
    doc_hash: str,
    n_paginas: int,
    textos_nativos: dict[int, str],
    textos_ocr: dict[int, str],
    spans: dict[int, "extracao.SpanPagina"],
    gate_ocr: dict[str, Any],
    modelo_ocr: Optional[str] = None,
) -> tuple[Optional[Any], Optional[str]]:
    """Costura + segmentação + bbox + `extractor_version` por página. **Puro**.

    Separado do `indexar` porque é a metade determinística: sem rede, sem
    modelo, sem relógio. É ela que os testes de determinismo e de mistura
    exercitam diretamente, sem dublar o mundo inteiro.

    A ORDEM da costura é o contrato: o texto do OCR **substitui** o nativo
    daquela página, nunca se soma a ele. Somar produziria a folha duas vezes —
    uma vez em carimbo (o que o extrator alcançou) e uma vez completa — e a
    segmentação criaria dois `sid` distintos para a mesma frase, quebrando a
    unicidade que torna a resolução O(1) confiável.
    """
    from garantis_shared.calculo_fichas.documento import (
        METODO_MISTO,
        METODO_NATIVE,
        METODO_OCR_GEMINI,
        DocumentoIndexado,
        DocumentoInvalidoError,
    )
    from garantis_shared.calculo_fichas.segmentacao import segmentar_paginas

    metodo_por_pagina: dict[int, str] = {}
    costurado: dict[int, str] = {}
    for pg in sorted(set(textos_nativos) | set(textos_ocr)):
        if pg in textos_ocr and textos_ocr[pg].strip():
            costurado[pg] = textos_ocr[pg]
            metodo_por_pagina[pg] = "ocr"
        else:
            costurado[pg] = textos_nativos.get(pg, "")
            metodo_por_pagina[pg] = "native"

    sentencas, paragrafos = segmentar_paginas(costurado)
    if not sentencas:
        return None, ERRO_VAZIO

    # bbox só nas páginas NATIVAS: o OCR devolve texto sem coordenada, e casar
    # texto de OCR contra spans do PyMuPDF apontaria para o carimbo que o
    # extrator alcançou — o lugar errado da imagem. `None` é o valor honesto.
    spans_nativos = {
        pg: sp for pg, sp in spans.items() if metodo_por_pagina.get(pg) != "ocr"
    }
    sentencas = extracao.atribuir_bboxes(sentencas, spans_nativos)

    n_ocr = sum(1 for m in metodo_por_pagina.values() if m == "ocr")
    if n_ocr == 0:
        metodo = METODO_NATIVE
        extractor_version = extracao.extractor_version_de("native")
    elif n_ocr == len([p for p in metodo_por_pagina if costurado.get(p, "").strip()]):
        metodo = METODO_OCR_GEMINI
        extractor_version = extracao.extractor_version_de("ocr", modelo_ocr=modelo_ocr)
    else:
        metodo = METODO_MISTO
        nativa = extracao.extractor_version_de("native")
        ocr_v = extracao.extractor_version_de("ocr", modelo_ocr=modelo_ocr)
        # Declara os DOIS: escolher um faria a outra metade mentir. O
        # `NORM_VERSION` sai dos componentes e fica no sufixo, uma vez só —
        # senão a string carregaria a mesma informação duas vezes e a chave de
        # cache ficaria sensível a uma ordem que não tem significado.
        extractor_version = (
            f"misto[{nativa.rsplit('+', 1)[0]}|{ocr_v.rsplit('+', 1)[0]}]"
            f"+{extracao.NORM_VERSION}"
        )

    gate_final = {
        **gate_ocr,
        "metodo_por_pagina": {str(p): m for p, m in sorted(metodo_por_pagina.items())},
        "extractor_version_por_pagina": {
            str(p): extracao.extractor_version_de(m, modelo_ocr=modelo_ocr)
            for p, m in sorted(metodo_por_pagina.items())
        },
        "paginas_ocr": sorted(p for p, m in metodo_por_pagina.items() if m == "ocr"),
    }

    try:
        return DocumentoIndexado(
            doc_id=doc_id,
            doc_hash=doc_hash,
            extractor_version=extractor_version,
            metodo=metodo,
            n_paginas=n_paginas,
            sentencas=tuple(sentencas),
            paragrafos=tuple(paragrafos),
            gate_ocr=gate_final,
        ), None
    except DocumentoInvalidoError as exc:
        logger.warning("[doc_indexer] %s: documento inválido: %r", doc_id, exc)
        return None, f"documento_invalido: {exc}"


# ── fontes de bytes ─────────────────────────────────────────────────────────

async def _obter_bytes(request: IndexarRequest) -> tuple[Optional[bytes], Optional[str]]:
    """`(pdf_bytes, None)` ou `(None, erro_tipado)`. GCS **ou** base64."""
    if request.pdf_base64:
        try:
            return base64.b64decode(request.pdf_base64, validate=True), None
        except Exception as exc:
            logger.warning("[doc_indexer] base64 inválido: %r", exc)
            return None, ERRO_BASE64
    if not request.gcs_path:
        return None, ERRO_SEM_FONTE

    # Reusa o fetch da casa: semáforo 5, sanity cap de 100MB, e o drop do stub
    # "acesso restrito" da jusbrasil (~46% dos PDFs de um processo real). Cada
    # um desses é um bug já pago.
    from .._utils.vision import fetch_pdfs_from_gcs

    try:
        baixados = await fetch_pdfs_from_gcs([request.gcs_path])
    except Exception as exc:
        logger.warning("[doc_indexer] fetch GCS falhou: %r", exc)
        return None, ERRO_DOWNLOAD
    if not baixados or not baixados[0]:
        return None, ERRO_DOWNLOAD
    return baixados[0], None


def _provider(nome: Optional[str]) -> Optional[Any]:
    """O provider do factory da casa — que honra `GEMINI_BACKEND`.

    `None` em vez de exceção: sem provider o documento ainda sai, nativo, com a
    lacuna declarada no `gate_ocr`. Um PDF de 300 folhas nativas não pode
    deixar de ser indexado porque as 2 folhas escaneadas do anexo não puderam
    ser lidas.
    """
    import os

    from ...providers import create_provider

    try:
        return create_provider(nome or os.getenv("DEFAULT_PROVIDER", "gemini"))
    except Exception as exc:
        logger.warning("[doc_indexer] provider indisponível: %r", exc)
        return None

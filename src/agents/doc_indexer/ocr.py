"""A ÚNICA chamada de LLM do pipeline de indexação — OCR das páginas que o gate acusou.

ONDA 2 do desenho (DESENHO-INVESTIGADOR-2026-08-13, §1.4 passo 4). *"O
pré-processamento é código determinístico + no máximo 1 chamada de OCR; não é
agente"* (LIÇÃO 5). Este módulo é essa uma chamada, e nada mais: ele não julga,
não resume, não decide o que ler. Recebe uma lista de páginas, devolve o texto
delas.

## O padrão vision da casa, reusado inteiro

    call_vision_l1(provider, model=…, prompt=…, pdf_bytes_list=[…])

`vision.py` já resolve o que importa e o RECON-ocr é explícito em mandar reusar:
roteador **inline vs Files API** por tamanho (15MB total / 5MB por PDF),
`types.Blob` com `bytes()` explícito, `_MAX_PDFS_PER_CALL`, `usage_metadata` →
`cost_usd` no envelope, e — o detalhe que mais importa aqui — **os PDFs ANTES
do prompt** nas `contents`. A ordem não é estilo: com o PDF depois da
instrução, a instrução vira contexto de um documento que o modelo ainda não
viu, e a taxa de "não consigo ler" sobe.

Dois débitos do `pdf_text.py` que esta frente NÃO herda (§1.4):
`_DEFAULT_GEMINI_MODEL = "gemini-2.5-flash-lite"` (família que aposenta em
16/10/2026) e `genai.Client(api_key=…)` direto, ignorando o kill-switch
`GEMINI_BACKEND`. Aqui o modelo vem do **ROLES** (`vision_fallback`) e o cliente
vem do `provider` do factory da casa, que honra o backend.

## Por que o OCR recebe um PDF RECORTADO

Mandar o PDF inteiro e pedir "transcreva as folhas 12 e 47" custa o documento
inteiro em tokens de input e depende de o modelo contar páginas certo — que é
exatamente o tipo de aritmética em que ele erra. Recortamos com o próprio
PyMuPDF: 1 chamada, N páginas, na ordem, e a página *i* da resposta é a página
*i* do recorte por construção. A conta de páginas volta a ser do código.

## O contrato de saída é DELIMITADO, não JSON

O prompt pede o texto entre marcadores `<<<PG:n>>>`, não um objeto JSON. Duas
razões: (a) transcrição literal de documento jurídico contém aspas, barras e
quebras que o JSON obriga a escapar, e cada escape é uma chance de o modelo
corromper o texto que a citação vai referenciar; (b) `response_schema` no turno
suprime qualidade em tarefa longa (§6.1) — e aqui não há decisão a tomar, só
texto a devolver. O parser é tolerante e o que ele não achar vira página vazia,
nunca um texto inventado no lugar errado.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "PAPEL_OCR",
    "PROMPT_VERSION",
    "modelo_ocr",
    "recortar_paginas",
    "montar_prompt_ocr",
    "parse_paginas_ocr",
    "ocr_paginas",
]

#: Papel do ROLES. `vision_fallback` já existe no catálogo do shared e é o mesmo
#: papel que o L1 usa para doc-imagem — o desenho (§8.4) registra `ficha_ocr`
#: como *proposta* apontando para o mesmo modelo, e trocar modelo de papel é
#: decisão do Elton (memory `engine-owns-model-control`). Enquanto `ficha_ocr`
#: não existir no ROLES, apontar para `vision_fallback` é o mesmo modelo com
#: uma decisão a menos tomada por conta própria.
PAPEL_OCR = "vision_fallback"

#: Versão do prompt de OCR. Entra na `extractor_version`? **Não** — entra na
#: chave de cache do Leitor (§7.1). Aqui ela serve à telemetria e ao dia em que
#: mudar o prompt exigir reindexar: bumpar isto e o `NORM_VERSION` juntos é o
#: gesto que orfana as âncoras antigas de propósito.
PROMPT_VERSION = "doc-indexer-ocr/v1"

#: Env override do modelo, no padrão da casa (`DEFAULT_MODEL` → papel → env
#: específica). O desenho (§8.4) nomeia `DOC_INDEXER_OCR_MODEL`.
_ENV_MODELO = "DOC_INDEXER_OCR_MODEL"

#: Marcador de página na resposta. Escolhido para não colidir com texto de
#: acórdão: `<<<` e `>>>` não aparecem em documento jurídico, e o `PG:` prefixa
#: um inteiro, então um falso positivo teria que ser literalmente `<<<PG:12>>>`.
_MARCADOR_RE = re.compile(r"<<<\s*PG\s*:\s*(\d+)\s*>>>")

#: Teto de páginas por chamada de OCR. Recorte grande estoura a janela e —
#: pior — degrada a transcrição no fim do documento sem nenhum erro. 30 é a
#: mesma ordem de grandeza do `AMOSTRA_PONTAS` do gate da casa.
MAX_PAGINAS_POR_CHAMADA = 30


def modelo_ocr() -> str:
    """O modelo do OCR: env específica → ROLES. **Nunca** hard-code.

    `model_for` levanta `KeyError` para papel inexistente, de propósito — papel
    desconhecido é bug de chamada, não um default silencioso. Mas OCR indisponível
    não pode derrubar a indexação de um PDF nativo, então quem chama trata: se
    este resolver falhar, o documento sai `metodo="native"` com as páginas
    inalcançáveis declaradas no `gate_ocr`. Melhor um documento com lacuna
    DECLARADA que um documento com lacuna silenciosa.
    """
    env = os.getenv(_ENV_MODELO)
    if env:
        return env
    from garantis_shared.llm_models import model_for

    return model_for(PAPEL_OCR)


def recortar_paginas(pdf_bytes: bytes, paginas: list[int]) -> Optional[bytes]:
    """PDF novo só com as `paginas` (1-based), na ordem crescente. `None` se falhar.

    PyMuPDF e não pypdf: o PDF já está aberto no caller com PyMuPDF e o
    `insert_pdf` preserva o conteúdo da página como está (é o mesmo motor). O
    pypdf entra no gate da casa só porque lá o recorte é de um PDF que ele não
    abriu.
    """
    if not paginas:
        return None
    try:
        import pymupdf

        origem = pymupdf.open(stream=bytes(pdf_bytes), filetype="pdf")
        destino = pymupdf.open()
        for p in sorted(paginas):
            idx = p - 1
            if 0 <= idx < len(origem):
                destino.insert_pdf(origem, from_page=idx, to_page=idx)
        if len(destino) == 0:
            return None
        return destino.tobytes()
    except Exception as exc:
        logger.warning("[doc_indexer] recorte de páginas falhou: %r", exc)
        return None


def montar_prompt_ocr(paginas: list[int]) -> str:
    """O prompt. Literal, sem interpretação, sem resumo — e diz por quê.

    A instrução mais importante é a de **não corrigir**: o modelo tem uma
    tendência forte a "consertar" número que parece errado e a completar
    abreviação, e no nosso caso o texto transcrito é o alvo do `sha_texto` da
    âncora e do `_assinatura_numerica` do gate G2. Uma correção bem-intencionada
    de `723.810.827,57` transforma a citação em algo que não está no documento —
    e o gate reprova a evidência CERTA.
    """
    ordenadas = sorted(paginas)
    lista = ", ".join(str(p) for p in ordenadas)
    linhas_marcador = "\n".join(f"<<<PG:{p}>>>" for p in ordenadas)
    return f"""Transcreva o texto das páginas deste PDF, na ordem.

O PDF anexado contém {len(ordenadas)} página(s), que correspondem — nesta ordem
— às folhas {lista} do documento original.

REGRAS DE TRANSCRIÇÃO (todas obrigatórias):

1. Transcreva LITERALMENTE. Não corrija, não normalize, não complete, não
   resuma, não traduza, não reordene. Se o documento escreve "R$ 723.810.827,57",
   transcreva exatamente esses caracteres — inclusive se o valor parecer errado.
2. Não interprete. Não escreva comentários, títulos, notas, nem qualquer texto
   que não esteja no documento.
3. Preserve as quebras de linha e de parágrafo como aparecem na página.
4. Tabelas: uma linha por linha da tabela, colunas separadas por " | ", com a
   linha de cabeçalho transcrita primeiro.
5. Página ilegível ou em branco: emita o marcador dela e deixe o conteúdo vazio.
   Nunca invente conteúdo para preencher.

FORMATO DA SAÍDA — exatamente este, sem nada antes nem depois:

{linhas_marcador}

Cada marcador é seguido pelo texto da folha correspondente. Emita todos os
{len(ordenadas)} marcadores, na ordem indicada, mesmo que alguma página esteja
vazia."""


def parse_paginas_ocr(resposta: str, paginas: list[int]) -> dict[int, str]:
    """`{pagina: texto}` a partir da resposta delimitada. Tolerante por desenho.

    Página cujo marcador não aparece **não entra no dicionário** — ela não vira
    `""`. A distinção importa: chave ausente significa "o OCR não devolveu esta
    folha" e o caller a declara no `gate_ocr` como não recuperada; `""`
    significaria "a folha está em branco", que é uma afirmação sobre o documento
    que não temos base para fazer.

    Texto antes do primeiro marcador é descartado (preâmbulo do modelo). Se
    NENHUM marcador aparecer e houver exatamente uma página pedida, a resposta
    inteira é atribuída a ela — é o modo de falha comum (modelo ignora o
    formato) e, com uma página só, não há ambiguidade sobre onde o texto vai.
    """
    if not resposta:
        return {}
    achados = list(_MARCADOR_RE.finditer(resposta))
    if not achados:
        if len(paginas) == 1:
            corpo = resposta.strip()
            return {paginas[0]: corpo} if corpo else {}
        logger.warning(
            "[doc_indexer] OCR devolveu 0 marcadores para %d páginas — descartado",
            len(paginas),
        )
        return {}

    pedidas = set(paginas)
    out: dict[int, str] = {}
    for i, m in enumerate(achados):
        try:
            pg = int(m.group(1))
        except (TypeError, ValueError):  # pragma: no cover — regex garante dígito
            continue
        if pg not in pedidas:
            # Marcador de página que não pedimos: o modelo inventou uma folha.
            # Aceitá-la escreveria texto de OCR sobre uma página nativa.
            logger.warning("[doc_indexer] OCR devolveu marcador de página não pedida: %d", pg)
            continue
        fim = achados[i + 1].start() if i + 1 < len(achados) else len(resposta)
        corpo = resposta[m.end():fim].strip()
        if corpo:
            out[pg] = corpo
    return out


async def ocr_paginas(
    provider: Any,
    pdf_bytes: bytes,
    paginas: list[int],
    *,
    model: Optional[str] = None,
) -> tuple[dict[int, str], dict[str, Any]]:
    """OCR das `paginas`. Devolve `({pagina: texto}, telemetria)`.

    Nunca levanta: qualquer falha devolve `({}, {...erro})` e o caller segue com
    o texto nativo, declarando a lacuna no `gate_ocr`. É o mesmo contrato do
    `call_l1_with_vision_fallback` (*"try/except → fallback text-only sem
    reraise"*, checklist do RECON-ocr) — o OCR é uma melhoria da leitura, não uma
    pré-condição dela, e derrubar a indexação de um PDF majoritariamente nativo
    porque 2 folhas anexadas não foram lidas seria trocar um número por nada.

    A telemetria (`model`, `cost_usd`, `paginas_pedidas`, `paginas_lidas`) sobe
    ao envelope da rota: custo invisível é o mecanismo que já escondeu US$ 97,61
    em 39.309 calls e reincidiu duas vezes.
    """
    tele: dict[str, Any] = {
        "model": None, "cost_usd": 0.0, "prompt_version": PROMPT_VERSION,
        "paginas_pedidas": len(paginas), "paginas_lidas": 0, "erro": None,
    }
    if not paginas:
        return {}, tele

    if len(paginas) > MAX_PAGINAS_POR_CHAMADA:
        logger.warning(
            "[doc_indexer] %d páginas para OCR > teto %d por chamada — cortando",
            len(paginas), MAX_PAGINAS_POR_CHAMADA,
        )
        paginas = sorted(paginas)[:MAX_PAGINAS_POR_CHAMADA]
        tele["paginas_pedidas"] = len(paginas)
        tele["truncado"] = True

    try:
        alvo = model or modelo_ocr()
    except Exception as exc:
        logger.warning("[doc_indexer] modelo de OCR não resolvido: %r", exc)
        tele["erro"] = f"modelo nao resolvido: {exc!r}"
        return {}, tele
    tele["model"] = alvo

    recorte = recortar_paginas(pdf_bytes, paginas)
    if not recorte:
        tele["erro"] = "recorte de páginas falhou"
        return {}, tele

    from .._utils.vision import call_vision_l1

    try:
        resposta = await call_vision_l1(
            provider,
            model=alvo,
            prompt=montar_prompt_ocr(paginas),
            pdf_bytes_list=[recorte],
            # SEM response_schema: transcrição literal não é decisão estruturada,
            # e o JSON obrigaria a escapar o texto que a citação referencia.
            response_schema=None,
            temperature=0.0,
            thinking_budget=0,
        )
    except Exception as exc:
        # Gemini 400 ("document has no pages"), timeout, quota — nada disso pode
        # derrubar a indexação. O documento sai nativo com a lacuna DECLARADA.
        logger.warning("[doc_indexer] chamada de OCR falhou: %r — segue no nativo", exc)
        tele["erro"] = repr(exc)
        return {}, tele

    meta = getattr(resposta, "metadata", None) or {}
    tele["cost_usd"] = float(meta.get("cost_usd") or 0.0)
    tele["model"] = getattr(resposta, "model", None) or alvo
    tele["input_tokens"] = getattr(resposta, "input_tokens", 0) or 0
    tele["output_tokens"] = getattr(resposta, "output_tokens", 0) or 0

    textos = parse_paginas_ocr(getattr(resposta, "text", "") or "", paginas)
    tele["paginas_lidas"] = len(textos)
    if len(textos) < len(paginas):
        tele["paginas_nao_lidas"] = sorted(set(paginas) - set(textos))
    return textos, tele

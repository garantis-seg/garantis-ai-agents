"""Gate de OCR **por página** — quais folhas o texto nativo não alcança.

ONDA 2 do desenho (DESENHO-INVESTIGADOR-2026-08-13, §1.4 passo 3).

## Este módulo NÃO é um gate novo

Ele é um *adaptador de granularidade* sobre `_utils/ocr_gate.py`, que é o gate
da casa e continua sendo a autoridade. Toda a régua — `texto_decide_sozinho`
(piso de TEOR via `garantis_shared.texto_util`), `texto_lixo` (rmgarbage
Taghva/ISRI), `_pagina_motivo` (área de texto → cobertura de imagem → vetor) —
vem de lá, importada. Nenhum threshold é redefinido aqui, e um fallback local
seria a sexta cópia do predicado que aquele módulo está justamente curando.

O que muda é a UNIDADE da resposta:

    ocr_gate.precisa_vision(texto, pdf)  → (manda: bool, nota)      por DOCUMENTO
    gate.paginas_inalcancaveis(doc, ...) → {pagina: motivo}         por PÁGINA

E a razão é de custo e de verdade. O consumidor do gate na casa hoje (o L1 do
mov/petição) decide se manda **o PDF inteiro** ao Gemini, então "o documento
precisa de vision" é a pergunta certa lá. Aqui o desenho é explícito (§1.4
passo 4): *"só as páginas inalcançáveis vão ao Gemini"*. Um acórdão de 300
páginas nativas com 2 folhas digitalizadas anexadas custaria 150× mais no
contrato de documento — e produziria `metodo="ocr_gemini"` para o documento
inteiro, dizendo ao humano que a citação da folha 12 é contra OCR quando ela é
contra o PDF real. Isso é mentir sobre a força da citação.

## As duas perguntas, e por que ambas

    1. o TEXTO daquela página decide sozinho?   → `texto_decide_sozinho`, Sinal 2 + TEOR
    2. a PÁGINA é alcançável por extrator?      → `_pagina_motivo`,        Sinal 1

Uma página só é declarada inalcançável quando **as duas** acusam. O Sinal 1
sozinho tem falso-positivo conhecido em folha de rosto e página de assinatura
(pouco texto, muito desenho) — mandar essas ao OCR é gasto sem retorno. O Sinal
2 sozinho é cego para scan limpo, que é a forma mais comum no acervo (o carimbo
do PJe / rodapé do ESAJ: português impecável, `garbage_ratio` ≈ 0, e a peça
presa na imagem — 8.597 documentos assim em prod).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from .._utils.ocr_gate import _pagina_motivo, texto_decide_sozinho

logger = logging.getLogger(__name__)

__all__ = [
    "MOTIVO_VAZIA",
    "MOTIVO_IMAGEM",
    "MOTIVO_VETOR",
    "paginas_inalcancaveis",
    "resumo_gate",
]

#: Motivos, repassados VERBATIM do `_pagina_motivo` do gate da casa. Ficam aqui
#: nomeados porque viram chave de telemetria (`gate_ocr["motivos"]`) e a
#: pergunta que se faz depois do flip é qual dos três cresceu — cada um tem
#: denominador de custo diferente.
MOTIVO_VAZIA = "vazia"
MOTIVO_IMAGEM = "imagem"
MOTIVO_VETOR = "vetor"


def paginas_inalcancaveis(
    doc: Any, textos: dict[int, str], *, teto_paginas: Optional[int] = None
) -> dict[int, str]:
    """`{pagina_1based: motivo}` das folhas que o texto nativo não alcança.

    `doc` é o `pymupdf.Document` já aberto (o caller já pagou o `open`; reabrir
    aqui seria o segundo parse do mesmo PDF). `textos` é o que
    `texto_nativo_por_pagina` extraiu — passado de fora, não relido, para que o
    gate julgue **exatamente** o texto que vai virar sentença. Reler produziria
    um segundo texto que pode divergir do primeiro e o gate julgaria outra coisa.

    `teto_paginas`, quando dado, limita quantas páginas podem ser marcadas.
    Existe porque o consumo de OCR é linear no número de folhas e um PDF
    inteiramente escaneado de 300 páginas é o caso onde o custo explode sem
    aviso — o caller (agent.py) o usa como teto duro e registra o corte no
    `gate_ocr`. Cortar é pior que não cortar? Sim, mas o corte é VISÍVEL
    (`truncado: true` + `paginas_nao_ocr`), enquanto a fatura não é.

    Falha em qualquer página ⇒ aquela página é considerada ALCANÇÁVEL (fica no
    nativo). É o fallback seguro do gate da casa: *"qualquer falha → trata como
    'não precisa Vision', nunca quebra"*. O contrário mandaria o documento
    inteiro ao Gemini sempre que o PyMuPDF tossisse.
    """
    try:
        import pymupdf
    except Exception:  # pragma: no cover — dep declarada
        return {}

    fora: dict[int, str] = {}
    for i, page in enumerate(doc, start=1):
        texto = textos.get(i, "")
        # Pergunta 1 — o texto desta folha se sustenta? Sai cedo no caso comum
        # (documento born-digital), evitando `get_images`/`get_drawings`, que
        # são as chamadas caras do Sinal 1.
        if texto_decide_sozinho(texto):
            continue
        # Pergunta 2 — e a página, é alcançável por extrator?
        try:
            motivo = _pagina_motivo(page, pymupdf)
        except Exception as exc:
            logger.warning("[doc_indexer] gate falhou na pg %d: %r — fica no nativo", i, exc)
            continue
        if motivo:
            fora[i] = motivo

    if teto_paginas is not None and len(fora) > teto_paginas:
        mantidas = sorted(fora)[:teto_paginas]
        logger.warning(
            "[doc_indexer] %d páginas inalcançáveis > teto %d — OCR só nas %d primeiras",
            len(fora), teto_paginas, teto_paginas,
        )
        return {p: fora[p] for p in mantidas}
    return fora


def resumo_gate(
    n_paginas: int, inalcancaveis: dict[int, str], *, truncado: bool = False
) -> dict[str, Any]:
    """O `gate_ocr` que vai gravado no `DocumentoIndexado` (§1.2).

    É a metade **write-time** da sentinela, e o desenho a exige pelo mesmo
    motivo que `call_l1_with_vision_fallback` exige o `gate_out`: sem ela, *"o
    gate não mandou nada"* e *"o gate nem rodou"* produzem exatamente o mesmo
    silêncio no banco. `motivos` discriminado (`imagem` × `vetor` × `vazia`)
    porque a pergunta depois do flip é qual ramo cresceu.
    """
    motivos: dict[str, int] = {}
    for m in inalcancaveis.values():
        motivos[m] = motivos.get(m, 0) + 1
    return {
        "n_paginas": n_paginas,
        "n_inalcancaveis": len(inalcancaveis),
        "paginas_inalcancaveis": sorted(inalcancaveis),
        "motivos": motivos,
        "truncado": truncado,
    }

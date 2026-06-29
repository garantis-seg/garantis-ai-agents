"""Mov Triage Agent — L1 v7, 1o estagio do desenho de 2 estagios.

UMA chamada LLM BARATA (prompt curto, gemini-2.5-flash-lite, temperature=0) que
responde os campos baratos + 2 PORTOES de roteamento:
  P1 mov_merito       — o ato decide algo OU traz tese/pedido/prova/desfecho?
  P2 mov_garantia_exec — toca garantia/apolice/deposito/acionamento OU avanca
                         execucao contra o Tomador? (REGRA DURA: na duvida true)

ROTEAMENTO (decidido pelo caller, NAO aqui): P1 ou P2 = true -> passe COMPLETO
(/mov-factsheet/classify). P1 e P2 = false -> ENXUTO (deriva o card por codigo).

Espelha classify_mov_factsheet, mas com prompt/schema da triagem e SEM o caminho
Vision (a triagem e text-only por design — roteamento barato). Fail-safe: card
malformado -> error dict, e o caller trata como "precisa completo".
"""

import json
import logging
import os
from typing import Optional

from ...providers import create_provider
from ...providers.base import LLMResponse
from ...utils.llm_json import parse_llm_json
from .._utils import MODEL_VARIANT_TEXT
from ..mov_factsheet.agent import _resumo_looks_like_json_meta_leak
from .prompts import build_mov_triage_prompt
from .schemas import (
    DocAnexado,
    FallbackContext,
    MovInput,
    MovTriageCard,
    ProcessoContext,
)

logger = logging.getLogger(__name__)

# Triagem roda SEMPRE no modelo mais barato — e o ponto do 1o estagio.
DEFAULT_MODEL = os.getenv("MOV_TRIAGE_MODEL", "gemini-2.5-flash-lite")
DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER", "gemini")

# Bump quando alterar build_mov_triage_prompt OR MovTriageCard schema.
# Usado pra drift detection em leads.engine_llm_calls.prompt_version.
#
# v1 (2026-06-04): porte do POC l1_triagem.py (build_triagem_prompt +
#   TRIAGEM_SCHEMA). Prompt curto (~5k chars), 2 portoes (mov_merito,
#   mov_garantia_exec), persona de triagem + regra de ouro.
PROMPT_VERSION = "mov_triage.v1"


async def classify_mov_triage(
    processo: ProcessoContext | dict,
    mov: MovInput | dict,
    documentos_anexados: list[DocAnexado | dict] | None = None,
    fallback_context: FallbackContext | dict | None = None,
    model: Optional[str] = None,
    provider: str = DEFAULT_PROVIDER,
) -> dict:
    """Triagem barata de UMA movimentacao. 1 LLM call, 6 campos.

    Args:
        processo: contexto minimo (CNJ, classe, polos)
        mov: id + data + tipo + texto da publicacao (snippet DJe)
        documentos_anexados: docs vinculados a essa mov
        fallback_context: paridade de assinatura com o factsheet (nao consumido)
        model: override Gemini model (default gemini-2.5-flash-lite)
        provider: 'gemini' (default)

    Returns:
        {"card": MovTriageCard.model_dump() | error_dict,
         "raw_response": str,
         "llm_raw_prompt": str,
         "prompt_version": str,
         "usage": dict}
    """
    if isinstance(processo, dict):
        processo = ProcessoContext(**processo)
    if isinstance(mov, dict):
        mov = MovInput(**mov)

    docs_typed: list[DocAnexado] = []
    for d in documentos_anexados or []:
        docs_typed.append(d if isinstance(d, DocAnexado) else DocAnexado(**d))

    fb_typed: FallbackContext | None = None
    if fallback_context is not None:
        fb_typed = (
            fallback_context
            if isinstance(fallback_context, FallbackContext)
            else FallbackContext(**fallback_context)
        )

    if model is None:
        model = DEFAULT_MODEL

    llm_provider = create_provider(provider)
    prompt = build_mov_triage_prompt(
        processo, mov,
        documentos_anexados=docs_typed,
        fallback_context=fb_typed,
    )

    # Triagem e text-only por design (roteamento barato, sem Vision).
    response: LLMResponse = await llm_provider.agenerate(
        prompt=prompt,
        model=model,
        temperature=0.0,
        response_schema=MovTriageCard,
        thinking_budget=0,
    )

    raw_response = response.text
    try:
        parsed = parse_llm_json(raw_response)
        card = MovTriageCard(**parsed)
        card_data = card.model_dump()
    except (json.JSONDecodeError, Exception) as e:
        logger.error(f"mov_triage parse failed mov_id={mov.mov_id}: {repr(e)}")
        card_data = {"error": repr(e), "raw": raw_response, "mov_id": mov.mov_id}

    # Leak guard (2026-06-29): mesma degeneração do mov_factsheet — JSON válido cujo VALOR
    # de resumo_ato é o meta-erro/inglês do modelo. NULL só o resumo_ato e mantém o card
    # (não devolver erro -> 500 -> engine retenta 6x à toa; esses movs degeneram em
    # flash-lite E flash). Front cai no texto cru do evento.
    if (isinstance(card_data, dict) and not card_data.get("error")
            and _resumo_looks_like_json_meta_leak(card_data.get("resumo_ato"))):
        logger.warning(
            "L1_TRIAGE_RESUMO_META_LEAK mov_id=%s -> resumo_ato=None (card mantido)",
            mov.mov_id,
        )
        card_data["resumo_ato"] = None

    usage = {
        "input_tokens": response.input_tokens or 0,
        "output_tokens": response.output_tokens or 0,
        "total_tokens": (response.input_tokens or 0) + (response.output_tokens or 0),
        "cost_usd": (response.metadata.get("cost_usd", 0.0) if response.metadata else 0.0),
        "model": model,
        "provider": provider,
        "model_variant": (
            response.metadata.get("model_variant", MODEL_VARIANT_TEXT)
            if response.metadata else MODEL_VARIANT_TEXT
        ),
    }

    return {
        "card": card_data,
        "raw_response": raw_response,
        "llm_raw_prompt": prompt,
        "prompt_version": PROMPT_VERSION,
        "usage": usage,
    }

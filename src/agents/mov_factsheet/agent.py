"""Mov FactSheet Agent — engine v6_meritos camada 1.

Single LLM call por movimentacao, extrai 13 campos estruturados.
Substitui mov_summarizer durante coexistencia (kind='mov_factsheet' vs kind='movimentacao').
"""

import json
import logging
import os
from typing import Optional

from ...providers import create_provider
from ...providers.base import LLMResponse
from ...utils.llm_json import parse_llm_json
from .prompts import build_mov_factsheet_prompt
from .schemas import (
    DocAnexado,
    FallbackContext,
    MovFactSheetCard,
    MovInput,
    ProcessoContext,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.getenv("MOV_FACTSHEET_MODEL", "gemini-2.5-flash-lite")
DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER", "gemini")


async def classify_mov_factsheet(
    processo: ProcessoContext | dict,
    mov: MovInput | dict,
    documentos_anexados: list[DocAnexado | dict] | None = None,
    fallback_context: FallbackContext | dict | None = None,
    model: Optional[str] = None,
    provider: str = DEFAULT_PROVIDER,
) -> dict:
    """Extract a 13-field FactSheet from a single mov.

    Args:
        processo: contexto minimo (CNJ, classe, polos)
        mov: id + data + tipo + texto da publicacao (snippet DJe)
        documentos_anexados: docs vinculados a essa mov (rota com doc text)
        fallback_context: passado SOMENTE quando documentos_anexados vazio
        model: override Gemini model
        provider: 'gemini' (default)

    Returns:
        {"card": MovFactSheetCard.model_dump() | error_dict, "raw_response": str, "usage": dict}
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
    prompt = build_mov_factsheet_prompt(
        processo, mov,
        documentos_anexados=docs_typed,
        fallback_context=fb_typed,
    )

    response: LLMResponse = await llm_provider.agenerate(
        prompt=prompt,
        model=model,
        temperature=0.0,
        response_schema=MovFactSheetCard,
    )

    raw_response = response.text
    try:
        parsed = parse_llm_json(raw_response)
        # Echo input identifiers em caso de LLM reset
        parsed.setdefault("mov_id", mov.mov_id)
        if mov.data and not parsed.get("data"):
            parsed["data"] = mov.data
        if mov.tipo and not parsed.get("tipo_origem"):
            parsed["tipo_origem"] = mov.tipo
        card = MovFactSheetCard(**parsed)
        card_data = card.model_dump()
    except (json.JSONDecodeError, Exception) as e:
        logger.error(f"mov_factsheet parse failed mov_id={mov.mov_id}: {repr(e)}")
        card_data = {"error": repr(e), "raw": raw_response, "mov_id": mov.mov_id}

    usage = {
        "input_tokens": response.input_tokens or 0,
        "output_tokens": response.output_tokens or 0,
        "total_tokens": (response.input_tokens or 0) + (response.output_tokens or 0),
        "cost_usd": (response.metadata.get("cost_usd", 0.0) if response.metadata else 0.0),
        "model": model,
        "provider": provider,
    }

    return {
        "card": card_data,
        "raw_response": raw_response,
        "usage": usage,
    }

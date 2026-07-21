"""Apolice Lifecycle Agent.

Single-step LLM call that reads movimentacoes processuais + apolice context
and classifies the lifecycle: apresentacao + aceitacao/recusa/pendente.
"""

import json
import logging
import os
from typing import Optional

from ...providers import create_provider
from ...providers.base import LLMResponse
from ...utils.llm_json import parse_llm_json
from .prompts import build_lifecycle_prompt
from .schemas import (
    ApoliceContext,
    ApoliceLifecycleResult,
    MovimentacaoInput,
)

logger = logging.getLogger(__name__)


# Trilha A (2026-07-21, OK Elton): 2.5-flash-lite -> 3.1-flash-lite (gold staging 16/26 vs 15/26).
# NUNCA usar gemini-3.1-flash NAO-lite — nao existe no Vertex (404).
DEFAULT_MODEL = os.getenv("APOLICE_LIFECYCLE_MODEL", "gemini-3.1-flash-lite")
DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER", "gemini")


async def classify_lifecycle(
    apolice: ApoliceContext | dict,
    processo_numero: str,
    movimentacoes: list[MovimentacaoInput] | list[dict],
    model: Optional[str] = None,
    provider: str = DEFAULT_PROVIDER,
) -> dict:
    """Classify apolice lifecycle within a processo.

    Args:
        apolice: ApoliceContext or dict (numero_apolice, seguradora, valor_is, vigência)
        processo_numero: CNJ formatado do processo
        movimentacoes: lista cronológica (mais antigas primeiro). Cap aplicado no prompt.
        model: override (default: gemini-2.5-flash-lite)
        provider: override (default: gemini)

    Returns:
        {
          "lifecycle": ApoliceLifecycleResult.model_dump() | error_dict,
          "raw_response": str,
          "usage": {input_tokens, output_tokens, cost_usd, model, provider}
        }
    """
    # Coerce dicts to Pydantic models if needed
    if isinstance(apolice, dict):
        apolice = ApoliceContext(**apolice)
    movs_typed: list[MovimentacaoInput] = []
    for m in movimentacoes:
        if isinstance(m, dict):
            movs_typed.append(MovimentacaoInput(**m))
        else:
            movs_typed.append(m)

    if model is None:
        model = DEFAULT_MODEL

    llm_provider = create_provider(provider)
    prompt = build_lifecycle_prompt(apolice, processo_numero, movs_typed)

    response: LLMResponse = await llm_provider.agenerate(
        prompt=prompt,
        model=model,
        temperature=0.0,
        response_schema=ApoliceLifecycleResult,
    )

    raw_response = response.text
    try:
        parsed_json = parse_llm_json(raw_response)
        lifecycle = ApoliceLifecycleResult(**parsed_json)
        lifecycle_data = lifecycle.model_dump()
    except (json.JSONDecodeError, Exception) as e:
        logger.error(f"Failed to parse lifecycle response for apolice={apolice.numero_apolice} "
                     f"processo={processo_numero}: {repr(e)}")
        lifecycle_data = {"error": repr(e), "raw": raw_response}

    usage = {
        "input_tokens": response.input_tokens or 0,
        "output_tokens": response.output_tokens or 0,
        "total_tokens": (response.input_tokens or 0) + (response.output_tokens or 0),
        "cost_usd": response.metadata.get("cost_usd", 0.0) if response.metadata else 0.0,
        "model": model,
        "provider": provider,
    }

    return {
        "lifecycle": lifecycle_data,
        "raw_response": raw_response,
        "usage": usage,
    }

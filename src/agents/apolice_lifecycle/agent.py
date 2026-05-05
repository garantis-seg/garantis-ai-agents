"""Apolice Lifecycle Agent.

Single-step LLM call that reads movimentacoes processuais + apolice context
and classifies the lifecycle: apresentacao + aceitacao/recusa/pendente.
"""

import json
import logging
import os
import re
from typing import Optional

from ...providers import create_provider
from ...providers.base import LLMResponse
from .prompts import build_lifecycle_prompt
from .schemas import (
    ApoliceContext,
    ApoliceLifecycleResult,
    MovimentacaoInput,
)

logger = logging.getLogger(__name__)


# Default to Flash Lite — cheap, fast, sufficient for structured extraction.
DEFAULT_MODEL = os.getenv("APOLICE_LIFECYCLE_MODEL", "gemini-2.5-flash-lite")
DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER", "gemini")


def _parse_llm_json(raw: str) -> dict:
    """Tolerant JSON parser (mirrors risk_classifier)."""
    text = (raw or "").strip()
    if not text:
        raise ValueError("empty LLM response")
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        msg = str(e)
        pos = getattr(e, "pos", None)
        if "Extra data" in msg and pos is not None:
            parsed = json.loads(text[:pos])
        elif "Unterminated string" in msg and pos is not None:
            last_comma = text.rfind(",", 0, pos)
            if last_comma > 0:
                parsed = json.loads(text[:last_comma] + "}")
            else:
                raise
        else:
            last_brace = text.rfind("}")
            if last_brace > 0:
                parsed = json.loads(text[:last_brace + 1])
            else:
                raise

    if isinstance(parsed, list):
        parsed = parsed[0] if parsed else {}
    if not isinstance(parsed, dict):
        raise ValueError(f"Expected JSON object, got {type(parsed).__name__}")
    return parsed


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
        parsed_json = _parse_llm_json(raw_response)
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

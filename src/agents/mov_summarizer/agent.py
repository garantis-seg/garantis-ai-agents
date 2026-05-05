"""Mov Summarizer Agent — single LLM call per movimentation."""

import json
import logging
import os
import re
from typing import Optional

from ...providers import create_provider
from ...providers.base import LLMResponse
from .prompts import build_mov_prompt
from .schemas import MovCardSummary, MovInput, ProcessoContext

logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.getenv("MOV_SUMMARIZER_MODEL", "gemini-2.5-flash-lite")
DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER", "gemini")


def _parse_llm_json(raw: str) -> dict:
    """Tolerant JSON parser (mirrors risk_classifier / apolice_lifecycle)."""
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


async def classify_mov(
    processo: ProcessoContext | dict,
    mov: MovInput | dict,
    model: Optional[str] = None,
    provider: str = DEFAULT_PROVIDER,
) -> dict:
    """Classify + summarize a single mov.

    Returns:
        {"card": MovCardSummary.model_dump() | error, "raw_response": str, "usage": dict}
    """
    if isinstance(processo, dict):
        processo = ProcessoContext(**processo)
    if isinstance(mov, dict):
        mov = MovInput(**mov)

    if model is None:
        model = DEFAULT_MODEL

    llm_provider = create_provider(provider)
    prompt = build_mov_prompt(processo, mov)

    response: LLMResponse = await llm_provider.agenerate(
        prompt=prompt,
        model=model,
        temperature=0.0,
        response_schema=MovCardSummary,
    )

    raw_response = response.text
    try:
        parsed = _parse_llm_json(raw_response)
        # Garantir que mov_id e data ecoem o input mesmo se LLM resetou
        parsed.setdefault("mov_id", mov.mov_id)
        if mov.data and not parsed.get("data"):
            parsed["data"] = mov.data
        if mov.tipo and not parsed.get("tipo_origem"):
            parsed["tipo_origem"] = mov.tipo
        card = MovCardSummary(**parsed)
        card_data = card.model_dump()
    except (json.JSONDecodeError, Exception) as e:
        logger.error(f"mov_summarizer parse failed mov_id={mov.mov_id}: {repr(e)}")
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

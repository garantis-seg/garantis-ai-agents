"""Court State Classifier Agent.

Single-step LLM call that reads (movement_text, current_state,
presentation_kind) e classifica o new_state em {offered, presumed_accepted,
accepted, rejected, replaced, closed} + closed_reason (4-enum) quando
new_state == 'closed'.

Default model: gemini-2.5-flash-lite, response_schema enforce structured
output (Literal enum no schema evita decoder loops).

Fase 2 upgrade do MVP regex em
`execucao-fiscal/frontend-api/services/court_presentation_inference_service.py`.
Worker gating via `USE_LLM_COURT_STATE_CLASSIFIER` env flag — default OFF.

Layer name pra telemetria: `court_presentation_inference` (já existe em
garantis-shared 1.70.0).
"""

import json
import logging
import os
from typing import Any, Optional

from ...providers import create_provider
from ...providers.base import LLMResponse
from ...utils.llm_json import parse_llm_json
from .prompts import (
    PROMPT_VERSION,
    TERMINAL_STATES,
    build_court_state_classifier_prompt,
)
from .schemas import CourtStateClassification, CourtStateClassifierRequest

logger = logging.getLogger(__name__)


# Trilha A (2026-07-21, OK Elton): 2.5-flash-lite -> 3.1-flash-lite (gold staging 16/26 vs 15/26).
# NUNCA usar gemini-3.1-flash NAO-lite — nao existe no Vertex (404).
DEFAULT_MODEL = os.getenv("COURT_STATE_CLASSIFIER_MODEL", "gemini-3.1-flash-lite")
DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER", "gemini")


async def classify_court_state(
    request: CourtStateClassifierRequest | dict,
    model: Optional[str] = None,
    provider: Optional[str] = None,
) -> dict:
    """Classify court_presentation target state via Gemini.

    Args:
        request: CourtStateClassifierRequest or dict with movement_text,
            current_state, presentation_kind, optional context.
        model: override (default: gemini-2.5-flash-lite via env).
        provider: override (default: gemini via env).

    Returns:
        {
          "classification": CourtStateClassification.model_dump() | error_dict,
          "raw_response": str,
          "prompt_version": str,
          "usage": {input_tokens, output_tokens, total_tokens, cost_usd,
                    model, provider, calls, model_variant}
        }
    """
    if isinstance(request, dict):
        request = CourtStateClassifierRequest(**request)

    if model is None:
        model = request.model or DEFAULT_MODEL
    if provider is None:
        provider = request.provider or DEFAULT_PROVIDER

    # Defensive guard — terminal state never transitions. Worker
    # provavelmente filtra antes (`ELIGIBLE_SOURCE_STATES_FOR_PROMOTION`),
    # mas se chegar aqui, retornamos no-op sem chamar LLM (zero cost).
    if request.current_state in TERMINAL_STATES:
        classification = CourtStateClassification(
            new_state=request.current_state,  # type: ignore[arg-type]
            confidence=1.0,
            reasoning="estado terminal — sem transição",
            closed_reason=None,
        )
        return {
            "classification": classification.model_dump(),
            "raw_response": None,
            "prompt_version": PROMPT_VERSION,
            "usage": {
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "cost_usd": 0.0,
                "model": model,
                "provider": provider,
                "calls": 0,
                "model_variant": "text",
            },
        }

    llm_provider = create_provider(provider)
    prompt = build_court_state_classifier_prompt(
        movement_text=request.movement_text,
        current_state=request.current_state,
        presentation_kind=request.presentation_kind,
        data_movimento=request.data_movimento,
        processo_numero=request.processo_numero,
    )

    try:
        response: LLMResponse = await llm_provider.agenerate(
            prompt=prompt,
            model=model,
            temperature=0.0,
            response_schema=CourtStateClassification,
        )
    except Exception as e:
        logger.error(
            "classify_court_state LLM call failed processo=%s current=%s: %r",
            request.processo_numero, request.current_state, e,
        )
        return {
            "classification": {"error": repr(e), "raw": None},
            "raw_response": None,
            "prompt_version": PROMPT_VERSION,
            "usage": {
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "cost_usd": 0.0,
                "model": model,
                "provider": provider,
                "calls": 1,
                "model_variant": "text",
            },
        }

    raw_response = response.text
    try:
        parsed_json = parse_llm_json(raw_response)
        classification = CourtStateClassification(**parsed_json)
        # Defensive: se LLM retornou closed sem closed_reason, normalizar
        # pra 'outra' (worker prefere classificação válida a None inesperado).
        if (
            classification.new_state == "closed"
            and classification.closed_reason is None
        ):
            logger.warning(
                "classify_court_state LLM returned closed without closed_reason — "
                "normalizing to 'outra' processo=%s",
                request.processo_numero,
            )
            classification.closed_reason = "outra"
        # Defensive: se non-closed veio com closed_reason, zerar.
        if (
            classification.new_state != "closed"
            and classification.closed_reason is not None
        ):
            classification.closed_reason = None
        classification_data = classification.model_dump()
    except (json.JSONDecodeError, Exception) as e:
        logger.error(
            "classify_court_state parse failed processo=%s current=%s: %r raw=%s",
            request.processo_numero, request.current_state, e,
            (raw_response or "")[:800],
        )
        classification_data = {
            "error": repr(e),
            "raw": (raw_response or "")[:800],
        }

    usage = _usage_from(response, model=model, provider=provider)

    return {
        "classification": classification_data,
        "raw_response": raw_response,
        "prompt_version": PROMPT_VERSION,
        "usage": usage,
    }


def _usage_from(response: LLMResponse, *, model: str, provider: str) -> dict[str, Any]:
    """Extract token + cost usage from LLMResponse (defensive)."""
    md = response.metadata or {}
    input_tokens = response.input_tokens or 0
    output_tokens = response.output_tokens or 0
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "cost_usd": md.get("cost_usd", 0.0),
        "model": model,
        "provider": provider,
        "calls": 1,
        "model_variant": md.get("model_variant", "text"),
    }

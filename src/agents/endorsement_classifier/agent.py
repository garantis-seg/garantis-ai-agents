"""Endorsement Classifier Agent.

Single-step LLM call that reads (objeto_segurado, prior_payload, new_payload,
diff_fields) e classifica o tipo do endosso em
{cancellation, extension, sum_insured_change, other}.

Default model: gemini-2.5-flash-lite, response_schema enforce structured
output (Literal enum no schema evita decoder loops).

Fase 2 upgrade do MVP regex em
`execucao-fiscal/frontend-api/services/apolice_derivation_service.py`. Worker
gating via `USE_LLM_ENDORSEMENT_CLASSIFIER` env flag — default OFF.
"""

import json
import logging
import os
from typing import Any, Optional

from ...providers import create_provider
from ...providers.base import LLMResponse
from ...utils.llm_json import parse_llm_json
from .prompts import PROMPT_VERSION, build_endorsement_classifier_prompt
from .schemas import EndorsementClassification, EndorsementClassifierRequest

logger = logging.getLogger(__name__)


DEFAULT_MODEL = os.getenv("ENDORSEMENT_CLASSIFIER_MODEL", "gemini-2.5-flash-lite")
DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER", "gemini")


async def classify_endorsement(
    request: EndorsementClassifierRequest | dict,
    model: Optional[str] = None,
    provider: Optional[str] = None,
) -> dict:
    """Classify endorsement type via Gemini.

    Args:
        request: EndorsementClassifierRequest or dict with prior_payload,
            new_payload, diff_fields, objeto_segurado, apolice_numero.
        model: override (default: gemini-2.5-flash-lite via env).
        provider: override (default: gemini via env).

    Returns:
        {
          "classification": EndorsementClassification.model_dump() | error_dict,
          "raw_response": str,
          "prompt_version": str,
          "usage": {input_tokens, output_tokens, total_tokens, cost_usd,
                    model, provider, calls, model_variant}
        }
    """
    if isinstance(request, dict):
        request = EndorsementClassifierRequest(**request)

    if model is None:
        model = request.model or DEFAULT_MODEL
    if provider is None:
        provider = request.provider or DEFAULT_PROVIDER

    llm_provider = create_provider(provider)
    prompt = build_endorsement_classifier_prompt(
        objeto_segurado=request.objeto_segurado,
        prior_payload=request.prior_payload,
        new_payload=request.new_payload,
        diff_fields=request.diff_fields,
        apolice_numero=request.apolice_numero,
    )

    try:
        response: LLMResponse = await llm_provider.agenerate(
            prompt=prompt,
            model=model,
            temperature=0.0,
            response_schema=EndorsementClassification,
        )
    except Exception as e:
        logger.error(
            "classify_endorsement LLM call failed apolice=%s: %r",
            request.apolice_numero, e,
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
        classification = EndorsementClassification(**parsed_json)
        classification_data = classification.model_dump()
    except (json.JSONDecodeError, Exception) as e:
        logger.error(
            "classify_endorsement parse failed apolice=%s diff=%s: %r raw=%s",
            request.apolice_numero, request.diff_fields, e,
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

"""
Risk Classifier Agent.

Classifies the activation risk of judicial guarantee bonds (seguro garantia)
based on recent court movements, using Daycoval's risk matrix criteria.

Uses Gemini 3 Flash for classification via the provider abstraction layer.
"""

import json
import os
import logging
from typing import Optional

from ...providers import create_provider
from ...providers.base import LLMResponse
from .schemas import RiskClassificationResult
from .prompts import build_risk_prompt

logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.getenv("RISK_CLASSIFIER_MODEL", "gemini-3-flash-preview")
DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER", "gemini")


async def classify_risk(
    processo_data: dict,
    movimentacoes: list[dict],
    cluster_processos: list[dict] | None = None,
    model: Optional[str] = None,
    provider: str = DEFAULT_PROVIDER,
) -> dict:
    """
    Classify bond activation risk based on court movements.

    Args:
        processo_data: Dict with nr_processo, materia, fase, vl_is_total, nm_tomador, etc.
        movimentacoes: List of movement dicts from Escavador API
        cluster_processos: Optional related processes with their movements
        model: Model name override (default: gemini-3-flash-preview)
        provider: LLM provider name (default: gemini)

    Returns:
        Dict with classification (RiskClassificationResult), raw_response, usage
    """
    llm_provider = create_provider(provider)

    if model is None:
        model = DEFAULT_MODEL

    prompt = build_risk_prompt(processo_data, movimentacoes, cluster_processos)

    response: LLMResponse = await llm_provider.agenerate(
        prompt=prompt,
        model=model,
        temperature=0.1,
        response_schema=RiskClassificationResult,
    )

    raw_response = response.text
    try:
        parsed_json = json.loads(raw_response)
        classification = RiskClassificationResult(**parsed_json)
    except (json.JSONDecodeError, Exception) as e:
        logger.error(f"Failed to parse risk classification response: {e}")
        classification = None
        parsed_json = {"error": str(e), "raw": raw_response}

    usage = {
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
        "total_tokens": response.total_tokens,
        "cost_usd": response.metadata.get("cost_usd", 0.0),
        "model": model,
        "provider": provider,
    }

    return {
        "classification": classification.model_dump() if classification else parsed_json,
        "raw_response": raw_response,
        "usage": usage,
    }


class RiskClassifierAgent:
    """Wrapper class for risk classification agent."""

    def __init__(
        self,
        provider: str = DEFAULT_PROVIDER,
        model: Optional[str] = None,
    ):
        self.provider = provider
        self.model = model or DEFAULT_MODEL

    async def classify(
        self,
        processo_data: dict,
        movimentacoes: list[dict],
        cluster_processos: list[dict] | None = None,
    ) -> dict:
        """Classify risk for a single process."""
        return await classify_risk(
            processo_data=processo_data,
            movimentacoes=movimentacoes,
            cluster_processos=cluster_processos,
            model=self.model,
            provider=self.provider,
        )

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
from .schemas import RiskClassificationResult, ProcessSummaryResult
from .prompts import build_risk_prompt, build_summary_prompt, build_classification_from_summary_prompt

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
    Classify bond activation risk using 2-step pipeline:
    1. Summarize: extract structured facts from raw movements
    2. Classify: apply risk criteria to structured summary

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

    total_input = 0
    total_output = 0

    # ── Step 1: Summarize movements into structured facts ──
    summary_prompt = build_summary_prompt(processo_data, movimentacoes, cluster_processos)

    summary_response: LLMResponse = await llm_provider.agenerate(
        prompt=summary_prompt,
        model=model,
        temperature=0.0,
        response_schema=ProcessSummaryResult,
    )

    total_input += summary_response.input_tokens or 0
    total_output += summary_response.output_tokens or 0

    try:
        summary = json.loads(summary_response.text)
        # Validate with pydantic
        ProcessSummaryResult(**summary)
    except (json.JSONDecodeError, Exception) as e:
        logger.warning(f"Summary parse failed, falling back to direct classification: {e}")
        # Fallback: direct classification without summary
        return await _classify_direct(llm_provider, processo_data, movimentacoes, cluster_processos, model, provider)

    logger.info(f"Summary for {processo_data.get('nr_processo')}: {summary.get('resumo_situacao', 'N/A')}")

    # ── Step 2: Classify based on structured summary ──
    classify_prompt = build_classification_from_summary_prompt(processo_data, summary)

    response: LLMResponse = await llm_provider.agenerate(
        prompt=classify_prompt,
        model=model,
        temperature=0.1,
        response_schema=RiskClassificationResult,
    )

    total_input += response.input_tokens or 0
    total_output += response.output_tokens or 0

    raw_response = response.text
    try:
        parsed_json = json.loads(raw_response)
        classification = RiskClassificationResult(**parsed_json)
    except (json.JSONDecodeError, Exception) as e:
        logger.error(f"Failed to parse risk classification response: {e}")
        classification = None
        parsed_json = {"error": str(e), "raw": raw_response}

    usage = {
        "input_tokens": total_input,
        "output_tokens": total_output,
        "total_tokens": total_input + total_output,
        "cost_usd": response.metadata.get("cost_usd", 0.0),
        "model": model,
        "provider": provider,
    }

    return {
        "classification": classification.model_dump() if classification else parsed_json,
        "summary": summary,
        "raw_response": raw_response,
        "usage": usage,
    }


async def _classify_direct(
    llm_provider, processo_data, movimentacoes, cluster_processos, model, provider,
) -> dict:
    """Fallback: single-step classification (used when summarizer fails)."""
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

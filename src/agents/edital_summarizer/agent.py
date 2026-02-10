"""
Edital Summarizer Agent.

Generates comprehensive structured summaries of government bidding documents (editais)
using LLM providers. Reads markdown content + metadata and returns a detailed JSON summary.
"""

import json
import logging
import os
from typing import Optional, Union

from ...providers import create_provider
from ...providers.base import LLMResponse
from .prompts import SYSTEM_PROMPT, build_user_prompt, format_items
from .schemas import (
    EditalMetadata,
    EditalSummaryLLMResponse,
    SummarizationRequest,
    SummarizationResponse,
)

logger = logging.getLogger(__name__)

DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER", "gemini")
DEFAULT_SUMMARIZATION_MODEL = os.getenv("DEFAULT_SUMMARIZATION_MODEL", "gemini-2.5-flash")


def _extract_json_from_text(text: str) -> dict:
    """Extract JSON from LLM response text, handling markdown blocks."""
    if not text or not text.strip():
        raise ValueError("Empty response text")

    text = text.strip()

    # Handle markdown code blocks
    if "```json" in text:
        start = text.find("```json") + 7
        end = text.find("```", start)
        text = text[start:end].strip()
    elif "```" in text:
        start = text.find("```") + 3
        end = text.find("```", start)
        text = text[start:end].strip()
    elif "{" in text and "}" in text:
        start = text.find("{")
        end = text.rfind("}") + 1
        text = text[start:end]

    return json.loads(text)


async def generate_summary(
    request: Union[SummarizationRequest, dict],
    provider: str = DEFAULT_PROVIDER,
    model: Optional[str] = None,
) -> SummarizationResponse:
    """
    Generate a comprehensive edital summary.

    Args:
        request: Summarization request with metadata + markdown content
        provider: LLM provider name
        model: Model to use (defaults to gemini-2.5-flash)

    Returns:
        SummarizationResponse with structured summary + metadata
    """
    if isinstance(request, dict):
        request = SummarizationRequest(**request)

    # Use request-level overrides if provided
    provider = request.provider or provider
    model = request.model or model or DEFAULT_SUMMARIZATION_MODEL

    # Build prompt
    metadata_dict = request.edital_metadata.model_dump()
    items_text = format_items(
        [item.model_dump() for item in request.edital_metadata.itens]
    )

    user_prompt = build_user_prompt(
        metadata=metadata_dict,
        items_text=items_text,
        markdown_content=request.markdown_content,
    )

    # Combine system + user prompt
    full_prompt = f"{SYSTEM_PROMPT}\n\n{user_prompt}"

    try:
        llm = create_provider(provider)

        response: LLMResponse = await llm.agenerate(
            prompt=full_prompt,
            model=model,
            temperature=0.1,
            max_tokens=8192,
            response_schema=EditalSummaryLLMResponse,
        )

        data = _extract_json_from_text(response.text)
        summary = EditalSummaryLLMResponse(**data)

        cost = response.metadata.get("cost_usd", 0.0) if response.metadata else 0.0

        return SummarizationResponse(
            summary=summary,
            model=model,
            provider=provider,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cost_usd=cost,
            success=True,
        )

    except Exception as e:
        logger.error(f"Edital summarization failed: {e}", exc_info=True)
        return SummarizationResponse(
            summary=EditalSummaryLLMResponse(),
            model=model,
            provider=provider,
            success=False,
            error=str(e),
        )


class EditalSummarizerAgent:
    """
    Agent wrapper for edital summarization.

    Provides a convenient interface for generating edital summaries
    with configurable provider and model.
    """

    def __init__(
        self,
        provider: str = DEFAULT_PROVIDER,
        model: Optional[str] = None,
    ):
        self.provider = provider
        self.model = model or DEFAULT_SUMMARIZATION_MODEL
        logger.info(
            f"EditalSummarizerAgent initialized: provider={provider}, model={self.model}"
        )

    async def summarize(
        self,
        request: Union[SummarizationRequest, dict],
    ) -> SummarizationResponse:
        """Generate a summary for an edital."""
        return await generate_summary(
            request=request,
            provider=self.provider,
            model=self.model,
        )

    def get_config(self) -> dict:
        """Get agent configuration."""
        return {
            "name": "edital_summarizer_agent",
            "provider": self.provider,
            "model": self.model,
            "description": "Generates comprehensive structured summaries of government bidding documents",
        }

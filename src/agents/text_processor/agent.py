"""
Text Processor Agent implementation.

AI-powered text processing including key information extraction.
"""

import logging
import os
from typing import List, Optional

from ...providers import LLMFactory
from .prompts import build_extraction_prompt
from .schemas import (
    KeyInfoExtractionResult,
    LLMExtractionResponse,
)

logger = logging.getLogger(__name__)

DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER", "gemini")
# Trilha A (2026-07-21, OK Elton): 2.5-flash-lite -> 3.1-flash-lite (gold staging 16/26 vs 15/26).
# NUNCA usar gemini-3.1-flash NAO-lite — nao existe no Vertex (404).
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "gemini-3.1-flash-lite")


async def extract_key_info(
    text: str,
    fields: List[str],
    context: Optional[str] = None,
    provider: str = DEFAULT_PROVIDER,
    model: Optional[str] = None,
) -> KeyInfoExtractionResult:
    """
    Extract key information from text.

    Args:
        text: Text to extract from
        fields: Fields to extract (e.g., ['cnpj', 'razao_social'])
        context: Additional context about the document
        provider: LLM provider
        model: Model to use

    Returns:
        KeyInfoExtractionResult with extracted fields
    """
    if not text.strip() or not fields:
        return KeyInfoExtractionResult(
            extracted_fields={f: None for f in fields},
            confidence={f: 0.0 for f in fields},
        )

    try:
        llm = LLMFactory.create_provider(provider)
        prompt = build_extraction_prompt(text, fields, context)

        response = await llm.generate_async(
            prompt=prompt,
            model=model,
            response_schema=LLMExtractionResponse,
        )

        if response.structured_output:
            result = response.structured_output
            return KeyInfoExtractionResult(
                extracted_fields=result.extracted_fields,
                confidence=result.confidence,
                success=True,
            )
        else:
            # Fallback: parse from text
            import json
            import re

            text_response = response.text.strip()

            # Remove markdown code blocks
            if text_response.startswith("```"):
                lines = text_response.split("\n")
                text_response = "\n".join(
                    lines[1:-1] if lines[-1] == "```" else lines[1:]
                )
                if text_response.startswith("json"):
                    text_response = text_response[4:].strip()

            data = json.loads(text_response)
            return KeyInfoExtractionResult(
                extracted_fields=data.get("extracted_fields", {}),
                confidence=data.get("confidence", {}),
                success=True,
            )

    except Exception as e:
        logger.error(f"Key info extraction failed: {e}")
        return KeyInfoExtractionResult(
            extracted_fields={f: None for f in fields},
            confidence={f: 0.0 for f in fields},
            success=False,
            error=str(e),
        )

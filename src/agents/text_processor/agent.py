"""
Text Processor Agent implementation.

AI-powered text processing including OCR correction, formatting, and extraction.
"""

import logging
import os
from typing import List, Optional

from ...providers import LLMFactory
from .prompts import (
    build_ocr_correction_prompt,
    build_formatting_prompt,
    build_extraction_prompt,
)
from .schemas import (
    KeyInfoExtractionResult,
    LLMExtractionResponse,
    OCRCorrectionResult,
    TextFormattingResult,
)

logger = logging.getLogger(__name__)

DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER", "gemini")
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "gemini-2.0-flash")

# Gemini token limit (~800K tokens, ~3.2M characters)
MAX_CHUNK_SIZE = 700_000  # characters per chunk


async def correct_ocr_text(
    text: str,
    preserve_structure: bool = True,
    language: str = "português brasileiro",
    provider: str = DEFAULT_PROVIDER,
    model: Optional[str] = None,
) -> OCRCorrectionResult:
    """
    Correct OCR errors in text.

    Args:
        text: Text to correct
        preserve_structure: Whether to preserve markdown/formatting
        language: Text language
        provider: LLM provider to use
        model: Model to use

    Returns:
        OCRCorrectionResult with corrected text
    """
    if not text.strip():
        return OCRCorrectionResult(
            original_length=0,
            corrected_length=0,
            corrected_text="",
            changes_made=False,
        )

    try:
        llm = LLMFactory.create_provider(provider)

        # Handle large documents by chunking
        if len(text) <= MAX_CHUNK_SIZE:
            corrected = await _correct_chunk(text, language, llm, model)
        else:
            # Process in chunks
            chunks = []
            for i in range(0, len(text), MAX_CHUNK_SIZE):
                chunk = text[i:i + MAX_CHUNK_SIZE]
                corrected_chunk = await _correct_chunk(chunk, language, llm, model)
                chunks.append(corrected_chunk)
            corrected = "".join(chunks)

        return OCRCorrectionResult(
            original_length=len(text),
            corrected_length=len(corrected),
            corrected_text=corrected,
            changes_made=corrected != text,
            success=True,
        )

    except Exception as e:
        logger.error(f"OCR correction failed: {e}")
        return OCRCorrectionResult(
            original_length=len(text),
            corrected_length=len(text),
            corrected_text=text,  # Return original on error
            changes_made=False,
            success=False,
            error=str(e),
        )


async def _correct_chunk(
    text: str,
    language: str,
    llm,
    model: Optional[str],
) -> str:
    """Correct a single chunk of text."""
    prompt = build_ocr_correction_prompt(text, language)

    response = await llm.generate_async(
        prompt=prompt,
        model=model,
    )

    return response.text.strip()


async def format_text(
    text: str,
    target_format: str = "markdown",
    preserve_line_breaks: bool = True,
    provider: str = DEFAULT_PROVIDER,
    model: Optional[str] = None,
) -> TextFormattingResult:
    """
    Format text to a specific format.

    Args:
        text: Text to format
        target_format: Target format ('markdown', 'plain', 'structured')
        preserve_line_breaks: Whether to preserve original line breaks
        provider: LLM provider
        model: Model to use

    Returns:
        TextFormattingResult with formatted text
    """
    if not text.strip():
        return TextFormattingResult(
            formatted_text="",
            format_applied=target_format,
        )

    try:
        llm = LLMFactory.create_provider(provider)
        prompt = build_formatting_prompt(text, target_format)

        response = await llm.generate_async(
            prompt=prompt,
            model=model,
        )

        return TextFormattingResult(
            formatted_text=response.text.strip(),
            format_applied=target_format,
            success=True,
        )

    except Exception as e:
        logger.error(f"Text formatting failed: {e}")
        return TextFormattingResult(
            formatted_text=text,
            format_applied="none",
            success=False,
            error=str(e),
        )


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


class TextProcessorAgent:
    """
    Agent for text processing tasks.

    Provides a class-based interface for text processing operations.
    """

    def __init__(
        self,
        provider: str = DEFAULT_PROVIDER,
        model: Optional[str] = None,
    ):
        """
        Initialize the text processor agent.

        Args:
            provider: LLM provider to use
            model: Model to use (defaults to provider's default)
        """
        self.provider = provider
        self.model = model
        self._llm = None

    @property
    def llm(self):
        """Lazy-load LLM provider."""
        if self._llm is None:
            self._llm = LLMFactory.create_provider(self.provider)
        return self._llm

    async def correct_ocr(
        self,
        text: str,
        preserve_structure: bool = True,
        language: str = "português brasileiro",
    ) -> OCRCorrectionResult:
        """
        Correct OCR errors in text.

        Args:
            text: Text to correct
            preserve_structure: Whether to preserve formatting
            language: Text language

        Returns:
            OCRCorrectionResult
        """
        return await correct_ocr_text(
            text=text,
            preserve_structure=preserve_structure,
            language=language,
            provider=self.provider,
            model=self.model,
        )

    async def format(
        self,
        text: str,
        target_format: str = "markdown",
        preserve_line_breaks: bool = True,
    ) -> TextFormattingResult:
        """
        Format text to a specific format.

        Args:
            text: Text to format
            target_format: Target format
            preserve_line_breaks: Preserve line breaks

        Returns:
            TextFormattingResult
        """
        return await format_text(
            text=text,
            target_format=target_format,
            preserve_line_breaks=preserve_line_breaks,
            provider=self.provider,
            model=self.model,
        )

    async def extract(
        self,
        text: str,
        fields: List[str],
        context: Optional[str] = None,
    ) -> KeyInfoExtractionResult:
        """
        Extract key information from text.

        Args:
            text: Text to extract from
            fields: Fields to extract
            context: Document context

        Returns:
            KeyInfoExtractionResult
        """
        return await extract_key_info(
            text=text,
            fields=fields,
            context=context,
            provider=self.provider,
            model=self.model,
        )

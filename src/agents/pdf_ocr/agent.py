"""
PDF OCR Agent - Convert scanned PDFs to Markdown using Gemini Vision.

Uses Gemini's native PDF understanding to extract text from scanned documents,
replacing the heavy marker-pdf/PyTorch/surya-ocr local OCR pipeline.
"""

import base64
import logging
import os
from typing import Optional

from ...providers import LLMFactory
from .prompts import PDF_TO_MARKDOWN_PROMPT
from .schemas import PdfOcrResult

logger = logging.getLogger(__name__)

DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER", "gemini")
# v2: gemini-2.5-flash-lite — newer/cheaper than 2.0-flash, good OCR quality
DEFAULT_OCR_MODEL = "gemini-2.5-flash-lite"


async def convert_pdf_to_markdown(
    pdf_bytes: bytes,
    filename: str = "document.pdf",
    model: Optional[str] = None,
    provider_name: str = DEFAULT_PROVIDER,
) -> PdfOcrResult:
    """
    Convert PDF bytes to Markdown using Gemini Vision.

    Sends the PDF as multimodal input to Gemini, which natively
    understands PDF pages as images and extracts text.

    Args:
        pdf_bytes: Raw PDF file bytes
        filename: Original filename (for logging)
        model: Gemini model to use (default: gemini-2.0-flash)
        provider_name: LLM provider (default: gemini)

    Returns:
        PdfOcrResult with markdown text and token usage
    """
    model = model or DEFAULT_OCR_MODEL

    if not pdf_bytes:
        return PdfOcrResult(
            success=False,
            error="Empty PDF bytes",
            model_used=model,
        )

    try:
        provider = LLMFactory.create_provider(provider_name)

        # Access the Gemini client and types directly for multimodal content
        client = provider._client
        types = provider._types

        # Build multimodal content: text prompt + PDF bytes
        text_part = types.Part.from_text(text=PDF_TO_MARKDOWN_PROMPT)
        pdf_part = types.Part(
            inline_data=types.Blob(
                mime_type="application/pdf",
                data=pdf_bytes,
            )
        )

        config = types.GenerateContentConfig(
            temperature=0.1,
            max_output_tokens=32768,
        )

        logger.info(f"[PDF-OCR] Sending {filename} ({len(pdf_bytes)} bytes) to Gemini Vision ({model})")

        response = await client.aio.models.generate_content(
            model=model,
            contents=[text_part, pdf_part],
            config=config,
        )

        # Extract token usage
        input_tokens = 0
        output_tokens = 0
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            input_tokens = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
            output_tokens = getattr(response.usage_metadata, "candidates_token_count", 0) or 0

        # Calculate cost
        pricing = provider.get_model_pricing(model)
        cost = (
            (input_tokens / 1_000_000) * pricing.get("input_per_1m", 0)
            + (output_tokens / 1_000_000) * pricing.get("output_per_1m", 0)
        )

        markdown_text = response.text.strip() if response.text else ""

        logger.info(
            f"[PDF-OCR] Success for {filename}: "
            f"{len(markdown_text)} chars, "
            f"{input_tokens} in / {output_tokens} out tokens, "
            f"${cost:.4f}"
        )

        return PdfOcrResult(
            markdown_text=markdown_text,
            page_count=0,  # Caller can set this (they have PyMuPDF)
            total_input_tokens=input_tokens,
            total_output_tokens=output_tokens,
            cost_usd=round(cost, 6),
            model_used=model,
            chunks_processed=1,
            success=True,
        )

    except Exception as e:
        error_msg = f"PDF OCR failed for {filename}: {type(e).__name__}: {e}"
        logger.error(error_msg)
        return PdfOcrResult(
            success=False,
            error=error_msg,
            model_used=model,
        )


class PdfOcrAgent:
    """
    Agent for PDF OCR conversion.

    Class-based interface for PDF-to-Markdown conversion.
    """

    def __init__(
        self,
        provider: str = DEFAULT_PROVIDER,
        model: Optional[str] = None,
    ):
        self.provider = provider
        self.model = model or DEFAULT_OCR_MODEL

    async def convert(
        self,
        pdf_bytes: bytes,
        filename: str = "document.pdf",
    ) -> PdfOcrResult:
        """Convert PDF to Markdown."""
        return await convert_pdf_to_markdown(
            pdf_bytes=pdf_bytes,
            filename=filename,
            model=self.model,
            provider_name=self.provider,
        )

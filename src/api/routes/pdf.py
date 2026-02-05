"""
Endpoints para conversao de PDF via OCR (Gemini Vision).
"""

import base64
import logging
import os
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...agents.pdf_ocr import PdfOcrResult, convert_pdf_to_markdown

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pdf", tags=["pdf"])

DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER", "gemini")


class PdfOcrRequest(BaseModel):
    """Request for PDF OCR conversion."""

    pdf_base64: str = Field(description="Base64-encoded PDF bytes")
    filename: str = Field(default="document.pdf", description="Original filename")
    model: Optional[str] = Field(default=None, description="Gemini model (default: gemini-2.0-flash)")
    provider: Optional[str] = Field(default=None, description="LLM provider (default: gemini)")


@router.post("/ocr", response_model=PdfOcrResult)
async def pdf_ocr_endpoint(request: PdfOcrRequest):
    """
    Convert a scanned PDF to Markdown using Gemini Vision.

    Accepts a base64-encoded PDF and returns high-quality Markdown text.
    Uses Gemini's native PDF understanding for OCR.

    For large PDFs (>25 pages), the caller should split into chunks
    and make multiple requests.
    """
    provider = request.provider or DEFAULT_PROVIDER

    try:
        pdf_bytes = base64.b64decode(request.pdf_base64)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid base64: {e}")

    if len(pdf_bytes) == 0:
        raise HTTPException(status_code=400, detail="Empty PDF")

    if len(pdf_bytes) > 50 * 1024 * 1024:  # 50MB limit
        raise HTTPException(status_code=400, detail="PDF exceeds 50MB limit")

    try:
        result = await convert_pdf_to_markdown(
            pdf_bytes=pdf_bytes,
            filename=request.filename,
            model=request.model,
            provider_name=provider,
        )
        return result
    except Exception as e:
        logger.exception(f"PDF OCR failed for {request.filename}")
        raise HTTPException(status_code=500, detail=str(e))

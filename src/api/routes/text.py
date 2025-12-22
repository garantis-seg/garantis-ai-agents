"""
Endpoints para processamento de texto.
"""

import logging
import os
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...agents.text_processor import (
    OCRCorrectionResult,
    TextFormattingResult,
    KeyInfoExtractionResult,
    correct_ocr_text,
    format_text,
    extract_key_info,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/text", tags=["text"])

DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER", "gemini")


# Request schemas


class CorrectOCRRequest(BaseModel):
    """Request for OCR text correction."""

    text: str = Field(description="Text to correct")
    preserve_structure: bool = Field(
        default=True, description="Preserve markdown/formatting structure"
    )
    language: str = Field(default="português brasileiro", description="Text language")
    provider: Optional[str] = Field(default=None, description="LLM provider to use")
    model: Optional[str] = Field(default=None, description="Model to use")


class FormatTextRequest(BaseModel):
    """Request for text formatting."""

    text: str = Field(description="Text to format")
    target_format: str = Field(
        default="markdown",
        description="Target format: 'markdown', 'plain', 'structured'"
    )
    preserve_line_breaks: bool = Field(default=True)
    provider: Optional[str] = Field(default=None)
    model: Optional[str] = Field(default=None)


class ExtractKeyInfoRequest(BaseModel):
    """Request for key information extraction."""

    text: str = Field(description="Text to extract information from")
    fields: List[str] = Field(
        description="Fields to extract (e.g., ['cnpj', 'razao_social', 'endereco'])"
    )
    context: Optional[str] = Field(
        default=None, description="Additional context about the document type"
    )
    provider: Optional[str] = Field(default=None)
    model: Optional[str] = Field(default=None)


# Endpoints


@router.post("/correct-ocr", response_model=OCRCorrectionResult)
async def correct_ocr_endpoint(request: CorrectOCRRequest):
    """
    Correct OCR errors in text.

    Fixes common OCR mistakes like:
    - Character substitutions (l→I, 0→O, rn→m)
    - Broken words
    - Incorrect spacing
    - Missing accents

    Preserves document structure and formatting.
    """
    provider = request.provider or DEFAULT_PROVIDER

    try:
        result = await correct_ocr_text(
            text=request.text,
            preserve_structure=request.preserve_structure,
            language=request.language,
            provider=provider,
            model=request.model,
        )
        return result
    except Exception as e:
        logger.exception("OCR correction failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/format", response_model=TextFormattingResult)
async def format_text_endpoint(request: FormatTextRequest):
    """
    Format text to a specific format.

    Supported formats:
    - markdown: Headers, lists, bold
    - plain: Simple text without formatting
    - structured: Organized sections with clear titles
    """
    provider = request.provider or DEFAULT_PROVIDER

    try:
        result = await format_text(
            text=request.text,
            target_format=request.target_format,
            preserve_line_breaks=request.preserve_line_breaks,
            provider=provider,
            model=request.model,
        )
        return result
    except Exception as e:
        logger.exception("Text formatting failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/extract", response_model=KeyInfoExtractionResult)
async def extract_key_info_endpoint(request: ExtractKeyInfoRequest):
    """
    Extract key information from text.

    Specify the fields you want to extract and optionally provide
    context about the document type for better results.

    Example fields: cnpj, razao_social, endereco, telefone, email
    """
    provider = request.provider or DEFAULT_PROVIDER

    try:
        result = await extract_key_info(
            text=request.text,
            fields=request.fields,
            context=request.context,
            provider=provider,
            model=request.model,
        )
        return result
    except Exception as e:
        logger.exception("Key info extraction failed")
        raise HTTPException(status_code=500, detail=str(e))

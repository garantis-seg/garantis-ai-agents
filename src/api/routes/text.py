"""
Endpoints para processamento de texto.
"""

import logging
import os
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...agents.text_processor import (
    KeyInfoExtractionResult,
    extract_key_info,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/text", tags=["text"])

DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER", "gemini")


# Request schemas


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

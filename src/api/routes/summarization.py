"""
Endpoints for edital summarization.
"""

import logging
import os
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...agents.edital_summarizer import generate_summary
from ...agents.edital_summarizer.schemas import (
    EditalMetadata,
    SummarizationRequest,
    SummarizationResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/summarization", tags=["summarization"])

DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER", "gemini")


class GenerateRequest(BaseModel):
    """Request body for summary generation."""

    edital_metadata: EditalMetadata = Field(description="Structured metadata from DB")
    markdown_content: str = Field(default="", description="Concatenated markdown content")
    provider: Optional[str] = Field(default=None, description="LLM provider override")
    model: Optional[str] = Field(default=None, description="Model override")


@router.post("/generate", response_model=SummarizationResponse)
async def generate_edital_summary(request: GenerateRequest):
    """
    Generate a comprehensive structured summary of an edital.

    Receives metadata + markdown content, calls LLM, returns structured JSON summary.
    Results are NOT cached here (caching is done by the caller, e.g. frontend-api).
    """
    try:
        summarization_request = SummarizationRequest(
            edital_metadata=request.edital_metadata,
            markdown_content=request.markdown_content,
            provider=request.provider,
            model=request.model,
        )

        result = await generate_summary(
            request=summarization_request,
            provider=request.provider or DEFAULT_PROVIDER,
            model=request.model,
        )

        if not result.success:
            raise HTTPException(
                status_code=500,
                detail=f"Summarization failed: {result.error}",
            )

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Summarization endpoint error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

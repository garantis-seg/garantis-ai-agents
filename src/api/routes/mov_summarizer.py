"""Endpoint pra classificar uma movimentação processual."""

import logging

from fastapi import APIRouter, HTTPException

from ...agents.mov_summarizer.agent import classify_mov
from ...agents.mov_summarizer.schemas import (
    MovSummarizerRequest,
    MovSummarizerResponse,
    MovCardSummary,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/mov-summarizer", tags=["mov-summarizer"])


@router.post("/classify", response_model=MovSummarizerResponse)
async def classify_mov_endpoint(request: MovSummarizerRequest):
    """Classify and summarize a single movement (mov) into a structured card.

    Output is compatible with dossier_artifacts kind='movimentacao' summary spec.
    """
    try:
        result = await classify_mov(
            processo=request.processo,
            mov=request.mov,
            model=request.model,
            provider=request.provider or "gemini",
        )
        card_data = result.get("card", {})
        if isinstance(card_data, dict) and "error" in card_data:
            raise HTTPException(status_code=500, detail=f"LLM parse error: {card_data.get('error')}")

        return MovSummarizerResponse(
            card=MovCardSummary(**card_data),
            raw_response=result.get("raw_response"),
            usage=result.get("usage", {}),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"mov_summarizer classify failed: {repr(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=repr(e))

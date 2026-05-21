"""Endpoint pro mov_factsheet agent (engine v6_meritos)."""

import logging

from fastapi import APIRouter, HTTPException

from ...agents.mov_factsheet.agent import classify_mov_factsheet
from ...agents.mov_factsheet.schemas import (
    MovFactSheetCard,
    MovFactSheetRequest,
    MovFactSheetResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/mov-factsheet", tags=["mov-factsheet"])


@router.post("/classify", response_model=MovFactSheetResponse)
async def classify_mov_factsheet_endpoint(request: MovFactSheetRequest):
    """Extract a 13-field FactSheet from a single movement.

    Output cabe em leads.dossier_artifacts com kind='mov_factsheet'.
    Usado pela engine v6_meritos como camada 1 de 3.
    """
    try:
        result = await classify_mov_factsheet(
            processo=request.processo,
            mov=request.mov,
            documentos_anexados=request.documentos_anexados,
            fallback_context=request.fallback_context,
            model=request.model,
            provider=request.provider or "gemini",
        )
        card_data = result.get("card", {})
        if isinstance(card_data, dict) and "error" in card_data:
            raise HTTPException(
                status_code=500,
                detail=f"LLM parse error: {card_data.get('error')}",
            )

        return MovFactSheetResponse(
            card=MovFactSheetCard(**card_data),
            raw_response=result.get("raw_response"),
            llm_raw_prompt=result.get("llm_raw_prompt"),
            prompt_version=result.get("prompt_version"),
            usage=result.get("usage", {}),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"mov_factsheet classify failed: {repr(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=repr(e))

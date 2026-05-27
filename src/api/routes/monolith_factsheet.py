"""Endpoint pro monolith_factsheet agent (engine v6_meritos, tier monolitico)."""
import logging

from fastapi import APIRouter, HTTPException

from ...agents.monolith_factsheet.agent import classify_monolith_factsheet
from ...agents.monolith_factsheet.schemas import (
    MonolithFactsheetCard,
    MonolithFactsheetRequest,
    MonolithFactsheetResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/monolith-factsheet", tags=["monolith-factsheet"])


@router.post("/classify", response_model=MonolithFactsheetResponse)
async def classify_monolith_factsheet_endpoint(request: MonolithFactsheetRequest):
    """Sintetiza PDF monolitico em 1 MonolithFactsheetCard.

    Output cabe em leads.dossier_artifacts com kind='monolith_factsheet',
    entity_type='processo', entity_id=processo_numero (digits-only). Usado
    pela engine v6_meritos como camada 1 quando o tier do proc eh
    'monolitico' (so lawsuit_pdfs.pre_extracted_text disponivel).
    """
    try:
        result = await classify_monolith_factsheet(
            processo=request.processo,
            autos_text=request.autos_text,
            total_pages=request.total_pages,
            pages_used=request.pages_used,
            truncated=request.truncated,
            model=request.model,
            provider=request.provider or "gemini",
            gcs_url=request.gcs_url,
        )
        card_data = result.get("card", {})
        if isinstance(card_data, dict) and "error" in card_data:
            raise HTTPException(
                status_code=500,
                detail=f"LLM parse error: {card_data.get('error')}",
            )

        return MonolithFactsheetResponse(
            card=MonolithFactsheetCard(**card_data),
            raw_response=result.get("raw_response"),
            llm_raw_prompt=result.get("llm_raw_prompt"),
            usage=result.get("usage", {}),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"monolith_factsheet classify failed: {repr(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=repr(e))

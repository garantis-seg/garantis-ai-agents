"""Endpoint pro day_factsheet agent (engine v6_meritos, tier Degradado-Dia)."""
import logging

from fastapi import APIRouter, HTTPException

from ...agents.day_factsheet.agent import classify_day_factsheet
from ...agents.day_factsheet.schemas import (
    DayFactsheetCard,
    DayFactsheetRequest,
    DayFactsheetResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/day-factsheet", tags=["day-factsheet"])


@router.post("/classify", response_model=DayFactsheetResponse)
async def classify_day_factsheet_endpoint(request: DayFactsheetRequest):
    """Sintetiza 1 dia inteiro de 1 processo correlacionando movs + docs.

    Output cabe em leads.dossier_artifacts com kind='day_factsheet',
    entity_id='{processo_numero}|{date}'. Usado pela engine v6_meritos como
    camada 1 quando o tier do proc eh Degradado-Dia.
    """
    try:
        result = await classify_day_factsheet(
            processo=request.processo,
            date=request.date,
            movs_no_dia=request.movs_no_dia,
            docs_no_dia=request.docs_no_dia,
            model=request.model,
            provider=request.provider or "gemini",
        )
        card_data = result.get("card", {})
        if isinstance(card_data, dict) and "error" in card_data:
            raise HTTPException(
                status_code=500,
                detail=f"LLM parse error: {card_data.get('error')}",
            )

        return DayFactsheetResponse(
            card=DayFactsheetCard(**card_data),
            raw_response=result.get("raw_response"),
            llm_raw_prompt=result.get("llm_raw_prompt"),
            usage=result.get("usage", {}),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"day_factsheet classify failed: {repr(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=repr(e))

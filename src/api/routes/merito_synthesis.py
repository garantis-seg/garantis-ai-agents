"""Endpoint pro merito_synthesis agent (engine v6_meritos camada 3 - OUTPUT PRIMARIO)."""

import logging

from fastapi import APIRouter, HTTPException

from ...agents.merito_synthesis.agent import classify_merito_synthesis
from ...agents.merito_synthesis.schemas import (
    MeritoSynthesisCard,
    MeritoSynthesisRequest,
    MeritoSynthesisResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/merito-synthesis", tags=["merito-synthesis"])


@router.post("/classify", response_model=MeritoSynthesisResponse)
async def classify_merito_synthesis_endpoint(request: MeritoSynthesisRequest):
    """Output primario da engine v6_meritos. Recebe processo_syntheses + tomador
    + cda/aiim + jurisprudencia + previous_snapshot. Retorna risco + justificativa
    + trajetoria + peca_pivo do merito.

    Persiste em monitoramento.risk_snapshots via orchestrator no frontend-api.
    """
    try:
        result = await classify_merito_synthesis(
            request=request,
            model=request.model,
            provider=request.provider or "gemini",
        )
        card_data = result.get("card", {})
        if isinstance(card_data, dict) and "error" in card_data:
            raise HTTPException(
                status_code=500,
                detail=f"LLM parse error: {card_data.get('error')}",
            )

        return MeritoSynthesisResponse(
            card=MeritoSynthesisCard(**card_data),
            raw_response=result.get("raw_response"),
            usage=result.get("usage", {}),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"merito_synthesis classify failed: {repr(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=repr(e))

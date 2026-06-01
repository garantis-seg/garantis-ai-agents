"""Endpoint pra classificar transição de estado de court_presentation."""

import logging

from fastapi import APIRouter, HTTPException

from ...agents.court_state_classifier.agent import classify_court_state
from ...agents.court_state_classifier.schemas import (
    CourtStateClassification,
    CourtStateClassifierRequest,
    CourtStateClassifierResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/court-state-classifier", tags=["court-state-classifier"])


@router.post("/classify", response_model=CourtStateClassifierResponse)
async def classify_court_state_endpoint(request: CourtStateClassifierRequest):
    """Classify court_presentation target state given movement_text + current_state.

    Returns:
        - new_state: offered|presumed_accepted|accepted|rejected|replaced|closed
        - confidence: 0.0-1.0
        - reasoning: short justification
        - closed_reason: extinto_processo|sinistro_pago|liberada|outra (only when closed)

    Fase 2 LLM upgrade do MVP regex worker
    (court_presentation_inference_service.py).
    """
    try:
        result = await classify_court_state(
            request=request,
            model=request.model,
            provider=request.provider or "gemini",
        )

        classification_data = result.get("classification", {})
        if isinstance(classification_data, dict) and "error" in classification_data:
            raise HTTPException(
                status_code=500,
                detail=f"LLM parse error: {classification_data.get('error')}",
            )

        return CourtStateClassifierResponse(
            classification=CourtStateClassification(**classification_data),
            raw_response=result.get("raw_response"),
            prompt_version=result.get("prompt_version"),
            usage=result.get("usage", {}),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Court state classifier failed: %r", e, exc_info=True)
        raise HTTPException(status_code=500, detail=repr(e))

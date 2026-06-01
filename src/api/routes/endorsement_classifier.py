"""Endpoint pra classificar tipo de endorsement de apolice."""

import logging

from fastapi import APIRouter, HTTPException

from ...agents.endorsement_classifier.agent import classify_endorsement
from ...agents.endorsement_classifier.schemas import (
    EndorsementClassification,
    EndorsementClassifierRequest,
    EndorsementClassifierResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/endorsement-classifier", tags=["endorsement-classifier"])


@router.post("/classify", response_model=EndorsementClassifierResponse)
async def classify_endorsement_endpoint(request: EndorsementClassifierRequest):
    """Classify endorsement type given prior/new payload + diff + objeto_segurado.

    Returns:
        - endorsement_type: cancellation|extension|sum_insured_change|other
        - confidence: 0.0-1.0
        - reasoning: short justification

    Fase 2 LLM upgrade do MVP regex worker (apolice_derivation_service.py).
    """
    try:
        result = await classify_endorsement(
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

        return EndorsementClassifierResponse(
            classification=EndorsementClassification(**classification_data),
            raw_response=result.get("raw_response"),
            prompt_version=result.get("prompt_version"),
            usage=result.get("usage", {}),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Endorsement classifier failed: %r", e, exc_info=True)
        raise HTTPException(status_code=500, detail=repr(e))

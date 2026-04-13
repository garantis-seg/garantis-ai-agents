"""Endpoints for risk classification of judicial guarantee bonds."""

import logging

from fastapi import APIRouter, HTTPException

from ...agents.risk_classifier.agent import classify_risk
from ...agents.risk_classifier.schemas import (
    RiskClassificationRequest,
    RiskClassificationResponse,
    RiskClassificationResult,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/risk-classification", tags=["risk-classification"])


@router.post("/classify", response_model=RiskClassificationResponse)
async def classify_risk_endpoint(request: RiskClassificationRequest):
    """
    Classify the activation risk of a judicial guarantee bond.

    Takes process metadata and recent court movements, returns risk level
    (Baixo/Medio/Alto/Altissimo), justification, and recommendation.
    """
    try:
        result = await classify_risk(
            processo_data=request.processo_data,
            movimentacoes=request.movimentacoes,
            provider=request.provider or "gemini",
            model=request.model,
        )

        classification_data = result.get("classification", {})
        if isinstance(classification_data, dict) and "error" in classification_data:
            raise HTTPException(
                status_code=500,
                detail=f"LLM parse error: {classification_data.get('error')}",
            )

        return RiskClassificationResponse(
            classification=RiskClassificationResult(**classification_data),
            usage=result.get("usage", {}),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Risk classification failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

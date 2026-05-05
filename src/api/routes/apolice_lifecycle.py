"""Endpoint pra classificar lifecycle de apolice em um processo."""

import logging

from fastapi import APIRouter, HTTPException

from ...agents.apolice_lifecycle.agent import classify_lifecycle
from ...agents.apolice_lifecycle.schemas import (
    ApoliceLifecycleRequest,
    ApoliceLifecycleResponse,
    ApoliceLifecycleResult,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/apolice-lifecycle", tags=["apolice-lifecycle"])


@router.post("/classify", response_model=ApoliceLifecycleResponse)
async def classify_lifecycle_endpoint(request: ApoliceLifecycleRequest):
    """Classify apolice lifecycle within a processo.

    Reads movimentacoes processuais + apolice context, returns:
    - apresentada (bool): whether apolice was presented
    - presented_at + evidence
    - acceptance_status: pendente|aceita|recusada|dispensada
    - acceptance_reason (when recusada)
    """
    try:
        result = await classify_lifecycle(
            apolice=request.apolice,
            processo_numero=request.processo_numero,
            movimentacoes=request.movimentacoes,
            model=request.model,
            provider=request.provider or "gemini",
        )

        lifecycle_data = result.get("lifecycle", {})
        if isinstance(lifecycle_data, dict) and "error" in lifecycle_data:
            raise HTTPException(
                status_code=500,
                detail=f"LLM parse error: {lifecycle_data.get('error')}",
            )

        return ApoliceLifecycleResponse(
            lifecycle=ApoliceLifecycleResult(**lifecycle_data),
            raw_response=result.get("raw_response"),
            usage=result.get("usage", {}),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Apolice lifecycle classification failed: {repr(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=repr(e))

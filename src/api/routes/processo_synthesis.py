"""Endpoint pro processo_synthesis agent (engine v6_meritos camada 2)."""

import logging

from fastapi import APIRouter, HTTPException

from ...agents.processo_synthesis.agent import classify_processo_synthesis
from ...agents.processo_synthesis.schemas import (
    ProcessoSynthesisCardRich,
    ProcessoSynthesisRequest,
    ProcessoSynthesisResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/processo-synthesis", tags=["processo-synthesis"])


@router.post("/classify", response_model=ProcessoSynthesisResponse)
async def classify_processo_synthesis_endpoint(request: ProcessoSynthesisRequest):
    """Synthesize a processo from its mov_factsheets + apolice context.

    Camada 2 da engine v6_meritos. Output cabe em dossier_artifacts kind='processo_synthesis'.
    Usado pela camada 3 (merito_synthesis) pra agregar risco no nivel do merito.
    """
    try:
        result = await classify_processo_synthesis(
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

        return ProcessoSynthesisResponse(
            # RICO (nao o base): preserva motivo_extincao/instrumento_cautelar/efeito_suspensivo
            # projetados em decisao_vigente — o base ProcessoSynthesisCard os stripa (extra=ignore).
            card=ProcessoSynthesisCardRich(**card_data),
            raw_response=result.get("raw_response"),
            llm_raw_prompt=result.get("llm_raw_prompt"),
            prompt_version=result.get("prompt_version"),
            usage=result.get("usage", {}),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"processo_synthesis classify failed: {repr(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=repr(e))

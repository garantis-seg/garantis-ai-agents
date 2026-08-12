"""Endpoint pro mov_factsheet agent (engine v6_meritos)."""

import logging

from fastapi import APIRouter, HTTPException

from ...agents.mov_factsheet.agent import classify_mov_factsheet
from ...agents.mov_factsheet.schemas import (
    MovFactSheetRequest,
    MovFactSheetResponse,
)
from ...agents.mov_triage.agent import classify_mov_triage
from ...agents.mov_triage.schemas import (
    MovTriageCard,
    TriageRequest,
    TriageResponse,
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
            classe=request.classe,
            documentos_gate=request.documentos_gate,
        )
        card_data = result.get("card", {})
        if isinstance(card_data, dict) and "error" in card_data:
            raise HTTPException(
                status_code=500,
                detail=f"LLM parse error: {card_data.get('error')}",
            )

        # card_data já validado dentro de classify (v3.1=MovFactSheetCard,
        # v4=MovFactSheetCardV4) — passa o dict direto, SEM re-coercir via
        # MovFactSheetCard (que dropava os fatos crus v4). Ver schemas.MovFactSheetResponse.
        return MovFactSheetResponse(
            card=card_data,
            raw_response=result.get("raw_response"),
            llm_raw_prompt=result.get("llm_raw_prompt"),
            prompt_version=result.get("prompt_version"),
            usage=result.get("usage", {}),
            vision_gate=result.get("vision_gate"),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"mov_factsheet classify failed: {repr(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=repr(e))


@router.post("/triage", response_model=TriageResponse)
async def triage_mov_endpoint(request: TriageRequest):
    """Triagem L1 v7 (1o estagio): 1 LLM call barata com 2 portoes de roteamento.

    Caller decide o roteamento: mov_merito OU mov_garantia_exec = true -> roda o
    passe COMPLETO em POST /mov-factsheet/classify. Ambos false -> deriva o card
    enxuto por codigo, sem 2a chamada LLM. Triagem malformada (HTTP 500) =
    fail-safe: o caller deve tratar como "precisa completo".
    """
    try:
        result = await classify_mov_triage(
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

        return TriageResponse(
            card=MovTriageCard(**card_data),
            raw_response=result.get("raw_response"),
            llm_raw_prompt=result.get("llm_raw_prompt"),
            prompt_version=result.get("prompt_version"),
            usage=result.get("usage", {}),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"mov_triage failed: {repr(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=repr(e))

"""Endpoint pro merito_synthesis agent (engine v6_meritos camada 3 - OUTPUT PRIMARIO)."""

import logging

from fastapi import APIRouter, HTTPException

from ...agents.merito_synthesis.agent import classify_merito_synthesis
from ...agents.merito_synthesis.redacao import redact_merito_synthesis
from ...agents.merito_synthesis.schemas import (
    MeritoSynthesisCardOut,
    MeritoSynthesisRequest,
    MeritoSynthesisResponse,
    RedacaoCard,
    RedacaoRequest,
    RedacaoResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/merito-synthesis", tags=["merito-synthesis"])


@router.post("/classify", response_model=MeritoSynthesisResponse)
async def classify_merito_synthesis_endpoint(request: MeritoSynthesisRequest):
    """Output primario da engine v6_meritos. Recebe processo_syntheses + tomador
    + cda + jurisprudencia + previous_snapshot. Retorna risco + justificativa
    + trajetoria + peca_pivo do merito. (Aiims saiu do payload na v2.8,
    2026-07-14 — teardown autos-wide; requests com aiims sao ignorados via
    extra='ignore'.)

    Persiste em monitoramento.risk_snapshots via orchestrator no frontend-api.
    """
    try:
        result = await classify_merito_synthesis(
            request=request,
            model=request.model,
            provider=request.provider or "gemini",
            bucket=request.bucket,
        )
        card_data = result.get("card", {})
        if isinstance(card_data, dict) and "error" in card_data:
            raise HTTPException(
                status_code=500,
                detail=f"LLM parse error: {card_data.get('error')}",
            )

        return MeritoSynthesisResponse(
            card=MeritoSynthesisCardOut(**card_data),  # COM ciclo_garantia (montado em código)
            raw_response=result.get("raw_response"),
            llm_raw_prompt=result.get("llm_raw_prompt"),
            prompt_version=result.get("prompt_version"),
            usage=result.get("usage", {}),
            bucket=result.get("bucket"),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"merito_synthesis classify failed: {repr(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=repr(e))


@router.post("/redacao", response_model=RedacaoResponse)
async def redacao_merito_synthesis_endpoint(request: RedacaoRequest):
    """L2 PROSA — passe de redacao. Recebe o risco JA decidido (risco_final) +
    os FATOS do merito; retorna SO a prosa (justificativa/narrativa/etc.),
    aplicando o <filtro_redacao_advogado> VERBATIM + guard prose_lint
    (retry -> fallback template). NAO re-decide o risco. Ver redacao.py.
    """
    try:
        result = await redact_merito_synthesis(
            request=request,
            model=request.model,
            provider=request.provider or "gemini",
        )
        return RedacaoResponse(
            card=RedacaoCard(**(result.get("card") or {})),
            raw_response=result.get("raw_response"),
            llm_raw_prompt=result.get("llm_raw_prompt"),
            prompt_version=result.get("prompt_version"),
            usage=result.get("usage", {}),
            prose_source=result.get("prose_source", "llm"),
            prose_leak_cats=result.get("prose_leak_cats", []),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"merito_synthesis redacao failed: {repr(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=repr(e))

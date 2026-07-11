"""Endpoint B1 — redução mérito-level de 1 passada (L3_MERITO_SYNTHESIS_V2).

O engine (risk-engine-worker) monta o dossiê coerente do mérito (DB) e POSTa aqui; este
serviço roda a CONVENTION do oráculo em gemini-3.5-flash + verify adversarial e devolve a
banda. Gated no engine (default OFF) — este endpoint é inerte até o materializer chamá-lo.
"""
import logging

from fastapi import APIRouter, HTTPException

from ...agents.merito_reducao_v2.agent import (
    MeritoReducaoV2Request,
    classify_merito_reducao_v2,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/merito-reducao-v2", tags=["merito-reducao-v2"])


@router.post("/classify")
async def classify_merito_reducao_v2_endpoint(request: MeritoReducaoV2Request):
    """Redução mérito-level de 1 passada. Recebe {merito_id, dossier, model?, run_verify?},
    retorna {card:{band,governing_process,decisive_doc_present,reasoning,citations,verify}, usage}.
    Parse-fail do LLM → card.error (engine trata como fail-clean → mantém L3 legado)."""
    try:
        result = await classify_merito_reducao_v2(
            request=request,
            model=request.model,
            provider=request.provider or "gemini",
        )
        return result
    except Exception as e:
        logger.error(f"merito_reducao_v2 classify failed: {repr(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=repr(e))

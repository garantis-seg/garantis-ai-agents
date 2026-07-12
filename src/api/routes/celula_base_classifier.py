"""Endpoint classificador de celula-base (D1).

O engine (risk-engine-worker) monta o dossie coerente do merito e POSTa aqui SO quando a banda do
B1 e Baixo e a flag CELULA_BASE_CLASSIFIER_ENABLED liga; roda N=3 leituras estreitas (seeds
variando) e devolve o sinal celula_base (unanime) que alimenta o piso deterministico do L3.
Gated no engine (default OFF) — inerte ate o materializer chamar.
"""
import logging

from fastapi import APIRouter, HTTPException

from ...agents.celula_base_classifier.agent import (
    CelulaBaseClassifyRequest,
    classify_celula_base,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/celula-base", tags=["celula-base"])


@router.post("/classify")
async def classify_celula_base_endpoint(request: CelulaBaseClassifyRequest):
    """Recebe {merito_id, dossier, model?, n?}, retorna {card:{celula_base: bool|None, unanimous,
    needs_review, votes_cb, votes_band, elton_band, governing_citation, reasoning, n_ok}, usage}.
    celula_base=None (split/votos insuficientes) => needs_review; o piso do L3 nunca floora nesse caso."""
    try:
        return await classify_celula_base(
            request=request,
            model=request.model,
            provider=request.provider or "gemini",
        )
    except Exception as e:
        logger.error(f"celula_base classify failed: {repr(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=repr(e))

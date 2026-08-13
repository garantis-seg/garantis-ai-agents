"""Endpoint do AUDITOR DE FICHA (S6) — `POST /ficha/auditar`.

Ultimo portao antes do S7 (persistir). Recebe a ficha ja redigida (S4) e
aprovada no deterministico (S5) mais o dossie congelado, e devolve o veredicto
no contrato de `garantis_shared.fichas.runner.auditar`.

Mesmo prefixo `/ficha` do ficha_writer de proposito: escrever e auditar a ficha
sao o mesmo recurso em dois momentos (`/ficha/write-fields`, `/ficha/auditar`).
"""

import logging

from fastapi import APIRouter, HTTPException

from ...agents.auditor_ficha import auditar_ficha
from ...agents.auditor_ficha.schemas import (
    AuditarFichaRequest,
    AuditarFichaResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ficha", tags=["ficha"])


@router.post("/auditar", response_model=AuditarFichaResponse)
async def auditar_endpoint(request: AuditarFichaRequest):
    """Audita a ficha contra o dossie e o checklist do Livro.

    Response: {success, aprovado, auditor_enabled, modelo, reprovacoes,
    pendencias, model, cost_usd, error?}.

    Falha de parse/validacao devolve 200 com `success=false`,
    `aprovado=false` e `auditor_enabled=false` — "nao auditada", que e
    diferente de reprovada e MUITO diferente de aprovada. Quem decide bloquear
    ou seguir e o runner do shared.
    """
    try:
        return await auditar_ficha(
            request=request,
            provider=request.provider,
            model=request.model,
        )
    except Exception as e:
        logger.error(f"auditor_ficha auditar failed: {repr(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=repr(e))

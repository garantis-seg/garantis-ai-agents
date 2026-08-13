"""Endpoints do C4 — calculador de grafo e auditor de evidencias.

Os dois passes do motor de calculo de garantia das fichas. O caller e o harness
do `garantis_shared.calculo_fichas`, que orquestra as rodadas: monta o payload,
chama `/montar-grafo`, verifica gramatica/evidencias/recomputo em codigo, chama
`/auditar-evidencias`, e devolve rejeicoes com historico ate aceitar ou esgotar
3 rodadas (⇒ grau indefinido, nunca numero forcado).

Nenhum dos dois endpoints produz um NUMERO: o calculador monta o grafo, o
auditor julga evidencias, e a aritmetica e do motor deterministico do shared.

Contrato de envelope como o write-fields: {success, ..., model, cost_usd}.
Falha de parse/validacao devolve success=false + error com 200 — o harness
decide a rodada. 500 fica so para falha inesperada de infraestrutura.
"""

import logging

from fastapi import APIRouter, HTTPException

from ...agents.auditor_evidencias import auditar_evidencias
from ...agents.auditor_evidencias.schemas import (
    AuditarEvidenciasRequest,
    AuditarEvidenciasResponse,
)
from ...agents.calculo_ficha import montar_grafo
from ...agents.calculo_ficha.schemas import MontarGrafoRequest, MontarGrafoResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/calculo-ficha", tags=["calculo-ficha"])


@router.post("/montar-grafo", response_model=MontarGrafoResponse)
async def montar_grafo_endpoint(request: MontarGrafoRequest):
    """Monta o GRAFO DE CELULAS da garantia, com evidencia citada por dado.

    O agente nao calcula: devolve celulas `dado`/`formula` que o motor
    deterministico do shared resolve. As premissas do V3, quando enviadas,
    entram como input read-only a re-verificar.

    Response: {success, celulas, evidencias, grau_sugerido, piso, teto,
    observacao, model, cost_usd, error?}.
    """
    try:
        return await montar_grafo(
            request=request, provider=request.provider, model=request.model,
        )
    except Exception as e:
        logger.error(f"calculo_ficha montar-grafo failed: {repr(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=repr(e))


@router.post("/auditar-evidencias", response_model=AuditarEvidenciasResponse)
async def auditar_evidencias_endpoint(request: AuditarEvidenciasRequest):
    """Julga cada evidencia: o trecho citado SUSTENTA o valor da celula?

    Adversarial (reprova na duvida) e com modelo diferente do calculador.
    Evidencia sem veredicto volta REPROVADA — silencio nunca vale aprovacao.

    Response: {success, veredictos, model, cost_usd, error?}.
    """
    try:
        return await auditar_evidencias(
            request=request, provider=request.provider, model=request.model,
        )
    except Exception as e:
        logger.error(f"calculo_ficha auditar-evidencias failed: {repr(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=repr(e))

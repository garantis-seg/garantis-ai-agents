"""Endpoint pro ficha_writer agent — escreve os slots de texto de uma ficha
de oportunidade (FichaJSON v2) a partir de um dossie de fatos.

Stateless: NUNCA produz numeros/datas/status — so texto dentro de limites duros.
A validacao dura de limite_chars fica com o caller (frontend-api); aqui so
reportamos presenca/tipo dos campos. Ver agents.ficha_writer.
"""

import logging

from fastapi import APIRouter, HTTPException

from ...agents.ficha_writer import write_ficha_fields
from ...agents.ficha_writer.schemas import (
    FichaWriteFieldsRequest,
    FichaWriteFieldsResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ficha", tags=["ficha"])


@router.post("/write-fields", response_model=FichaWriteFieldsResponse)
async def write_fields_endpoint(request: FichaWriteFieldsRequest):
    """Escreve os SLOTS DE TEXTO da ficha a partir do dossie de fatos.

    Response: {success, campos, model, cost_usd, error?}. Em falha de
    parse/tipo/campo faltando devolve success=false + error claro (200) — o
    caller decide o retry (inclusive reenviando via `campos_com_erro`).
    """
    try:
        return await write_ficha_fields(
            request=request,
            provider=request.provider,
            model=request.model,
        )
    except Exception as e:
        logger.error(f"ficha_writer write-fields failed: {repr(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=repr(e))

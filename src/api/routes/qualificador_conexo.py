"""Endpoint da S2c — qualificar o conexo (card 869ffv22t).

    POST /ficha/qualificar-conexo

Mesmo prefixo `/ficha` do writer e do auditor de ficha: as 3 rotas tratam do
mesmo recurso em momentos diferentes. Os paths não colidem.

Códigos de resposta:

- 200: a qualificação passou nas regras duras. O corpo é `QualificarConexoResponse`.
- 422 com `{"detail": {"erro": "qualificacao_invalida", "erros": [{campo, erro,
  valor_anterior}], ...}}`: a emissão do LLM falhou nas regras duras depois de 2
  rodadas de correção. O chamador pode tentar de novo.
- 422 com `{"detail": [...]}` (lista): o FastAPI recusou a ENTRADA (chave extra,
  enum errado). O chamador tem de corrigir o pedido. Não tente de novo igual.
- 500: falha de infraestrutura (provider fora do ar, por exemplo).
"""

import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from ...agents.qualificador_conexo import (
    QualificacaoInvalidaError,
    QualificarConexoRequest,
    QualificarConexoResponse,
    qualificar_conexo,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ficha", tags=["ficha"])


@router.post("/qualificar-conexo", response_model=QualificarConexoResponse)
async def qualificar_conexo_endpoint(request: QualificarConexoRequest):
    """S2c: é fiscal? e qual é o estado de cada garantia? Sempre com prova literal."""
    try:
        return await qualificar_conexo(request)
    except QualificacaoInvalidaError as e:
        logger.info("qualificar-conexo 422 conexo=%s erros=%d",
                    request.conexo_id, len(e.body.erros))
        return JSONResponse(status_code=422, content={"detail": e.body.model_dump()})
    except Exception as e:
        logger.error(f"qualificar-conexo failed: {repr(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=repr(e))

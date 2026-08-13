"""Endpoint do VERIFICADOR CEGO (onda 9) — POST /calculo-ficha/verificar-par.

Vive em arquivo SEPARADO do `calculo_ficha.py` de proposito: o modo cego e
ADITIVO e o `/auditar-evidencias` continua servindo o harness de hoje. Dois
routers com o mesmo `prefix` montam no mesmo espaco de caminhos — do lado do
cliente `/calculo-ficha/verificar-par` e `/calculo-ficha/auditar-evidencias`
sao vizinhos, e nenhum PR precisa tocar no arquivo do outro para nascer.

Contrato de envelope da casa: `{success, ..., model, cost_usd}`. Falha de
parse/validacao devolve `success=false` com **HTTP 200** — o harness decide a
rodada; 500 fica so para falha inesperada de infraestrutura.
"""

import logging

from fastapi import APIRouter, HTTPException

from ...agents.auditor_evidencias.verificador import verificar_par
from ...agents.auditor_evidencias.verificador_schemas import (
    VerificarParRequest,
    VerificarParResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/calculo-ficha", tags=["calculo-ficha"])


@router.post("/verificar-par", response_model=VerificarParResponse)
async def verificar_par_endpoint(request: VerificarParRequest):
    """Julga UM par as cegas: este trecho sustenta esta afirmacao?

    O verificador ve `{afirmacao, ancora, trecho}` e mais nada — sem grafo, sem
    documento inteiro, sem historico de construcao (DESENHO §2.3: contexto no
    verificador inflou falsos positivos ~5x no HALLMARK).

    Devolve QUATRO rotulos, nao dois (`supported`/`partial`/`contradicted`/
    `irrelevant`), porque cada um manda o problema para uma fila com dono
    diferente, e `motivo_tipado` de enum FECHADO, porque o QA agrega por ele.
    `numeros_divergentes` sai do CODIGO, nao do modelo.

    Response: {success, veredito, motivo_tipado, numeros_divergentes, confianca,
    objeto_da_confianca, votos, self_consistency_n, model, cost_usd, error?}.
    """
    try:
        return await verificar_par(
            request=request, provider=request.provider, model=request.model,
        )
    except Exception as e:
        logger.error(f"calculo_ficha verificar-par failed: {repr(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=repr(e))

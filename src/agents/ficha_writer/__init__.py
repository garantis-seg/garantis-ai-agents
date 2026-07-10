"""ficha_writer agent — escreve os SLOTS DE TEXTO de uma ficha de oportunidade
(FichaJSON v2) a partir de um dossie de fatos.

Endpoint stateless: NUNCA produz numeros/datas/status — so texto dentro de
limites duros de caracteres. O caller (frontend-api) valida os limites e decide
retry. Ver agent.write_ficha_fields + api.routes.ficha_writer.
"""

from .agent import write_ficha_fields
from .schemas import (
    CampoComErro,
    CampoSpec,
    FichaWriteFieldsRequest,
    FichaWriteFieldsResponse,
)

__all__ = [
    "write_ficha_fields",
    "CampoSpec",
    "CampoComErro",
    "FichaWriteFieldsRequest",
    "FichaWriteFieldsResponse",
]

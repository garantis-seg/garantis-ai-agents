"""ficha_writer agent — escreve os SLOTS DE TEXTO de uma ficha de oportunidade
(FichaJSON v2). Etapa S4 da esteira de fichas.

O agente NUNCA produz número, data nem status. Ele redige texto dentro do limite de
cada slot. No v4 (request com `esqueleto`), ele segue o Livro da Ficha por slot × tipo,
trata o esqueleto como fato fixo, responde os alertas do código e valida a saída. Ver
`README.md` nesta pasta.
"""

from .agent import MAX_RODADAS, write_ficha_fields
from .schemas import (
    Alerta,
    AlertaRespondido,
    CampoComErro,
    CampoSpec,
    ErroDeCampo,
    Esqueleto,
    FichaWriteFieldsRequest,
    FichaWriteFieldsResponse,
)

__all__ = [
    "MAX_RODADAS",
    "write_ficha_fields",
    "Alerta",
    "AlertaRespondido",
    "CampoSpec",
    "CampoComErro",
    "ErroDeCampo",
    "Esqueleto",
    "FichaWriteFieldsRequest",
    "FichaWriteFieldsResponse",
]

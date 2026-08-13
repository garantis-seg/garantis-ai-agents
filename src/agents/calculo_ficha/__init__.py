"""calculo_ficha agent — CALCULADOR do C4.

Monta o GRAFO DE CELULAS (dado|formula) de uma garantia, com evidencia citada
por dado. NAO calcula o numero: o motor deterministico do
`garantis_shared.calculo_fichas` resolve o grafo, confere as evidencias contra
o texto dos documentos, recomputa e so entao aceita.

Ver agent.montar_grafo + api.routes.calculo_ficha.
"""

from .agent import montar_grafo
from .schemas import (
    CelulaDado,
    CelulaFormula,
    Evidencia,
    MontarGrafoRequest,
    MontarGrafoResponse,
)

__all__ = [
    "montar_grafo",
    "CelulaDado",
    "CelulaFormula",
    "Evidencia",
    "MontarGrafoRequest",
    "MontarGrafoResponse",
]

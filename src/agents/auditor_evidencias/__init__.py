"""auditor_evidencias agent — AUDITOR do C4.

Julga, evidencia por evidencia, se o trecho citado SUSTENTA o valor da celula.
A existencia do trecho no documento ja foi provada por codigo (shared:
`evidencias.verificar_evidencias`); aqui a pergunta e semantica.

Adversarial por desenho (default = reprovar na duvida) e com modelo DIFERENTE
do calculador. Ver agent.auditar_evidencias + api.routes.calculo_ficha.
"""

from .agent import auditar_evidencias
from .schemas import (
    AuditarEvidenciasRequest,
    AuditarEvidenciasResponse,
    Veredicto,
)

__all__ = [
    "auditar_evidencias",
    "AuditarEvidenciasRequest",
    "AuditarEvidenciasResponse",
    "Veredicto",
]

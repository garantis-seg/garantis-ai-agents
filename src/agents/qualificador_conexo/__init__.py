"""qualificador_conexo — o agente da S2c (card 869ffv22t).

Responde 2 perguntas sobre um conexo, sempre com prova literal:

1. Cada processo é fiscal?
2. Qual é o estado de cada garantia: ativa, substituida, liberada ou sem_evidencia?

Ver `README.md` desta pasta, `agent.qualificar_conexo` e
`api.routes.qualificador_conexo`.
"""

from .agent import QualificacaoInvalidaError, qualificar_conexo
from .schemas import QualificarConexoRequest, QualificarConexoResponse

__all__ = [
    "QualificacaoInvalidaError",
    "QualificarConexoRequest",
    "QualificarConexoResponse",
    "qualificar_conexo",
]

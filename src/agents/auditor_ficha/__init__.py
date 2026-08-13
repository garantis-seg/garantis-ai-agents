"""auditor_ficha agent — o AUDITOR DE FICHA (step S6 do pipeline de fichas).

Ultimo portao antes de a ficha ser persistida: confere a ficha redigida pelo S4
(ja aprovada no S5 deterministico) contra o DOSSIE e contra o checklist do Livro
da Ficha. So julga o que NAO e mecanizavel — fidelidade factual, afirmacao sem
lastro, vocabulario proibido em contexto e coerencia entre secoes. Limite de
caracteres, enum, DV de CNPJ e formato de data sao travas do S5 e nunca chegam
aqui.

Saida no contrato EXATO de `garantis_shared.fichas.runner.auditar`:
{aprovado, auditor_enabled, modelo, reprovacoes[{campo, motivo, regra}], cost_usd}.
Reprovacao e TIPADA e ancorada num ID do Livro — nunca nota ou score.

Ver agent.auditar_ficha + api.routes.auditor_ficha.
"""

from .agent import auditar_ficha, resolver_modelo
from .schemas import (
    AuditarFichaRequest,
    AuditarFichaResponse,
    Reprovacao,
)

__all__ = [
    "auditar_ficha",
    "resolver_modelo",
    "AuditarFichaRequest",
    "AuditarFichaResponse",
    "Reprovacao",
]

"""Mov Triage Agent (L1 v7 — triagem 2-estagios, 1o estagio).

UMA chamada LLM barata (gemini-2.5-flash-lite, prompt curto) que classifica o ato
e responde 2 PORTOES de roteamento (mov_merito, mov_garantia_exec). Caller decide:
algum portao true -> passe COMPLETO (/mov-factsheet/classify); ambos false ->
deriva o card enxuto por codigo (sem 2a chamada LLM).

REGRA DE OURO: a triagem so erra pro lado SEGURO (na duvida -> completo).
"""

from .agent import classify_mov_triage
from .schemas import (
    DocAnexado,
    FallbackContext,
    MovInput,
    MovTriageCard,
    ProcessoContext,
    TriageRequest,
    TriageResponse,
)

__all__ = [
    "classify_mov_triage",
    "DocAnexado",
    "FallbackContext",
    "MovInput",
    "MovTriageCard",
    "ProcessoContext",
    "TriageRequest",
    "TriageResponse",
]

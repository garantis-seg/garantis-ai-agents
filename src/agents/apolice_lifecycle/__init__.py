"""Apolice Lifecycle Agent.

Extracts the lifecycle of a seguro garantia apolice within a specific judicial
processo, by reading the movimentacoes (court movements) and identifying:

- When the apolice was presented (apresentada)
- Whether it was accepted, refused, or is still pending (acceptance_status)
- The reason for refusal if applicable

This is Fase 2 of the risk-engine-cards-cliente plan. The lifecycle signal is
load-bearing for cliente Poletto (presented_at + acceptance_status are direct
inputs to the risk classifier in v5).
"""

from .agent import classify_lifecycle
from .schemas import (
    ApoliceLifecycleRequest,
    ApoliceLifecycleResponse,
    ApoliceLifecycleResult,
)

__all__ = [
    "classify_lifecycle",
    "ApoliceLifecycleRequest",
    "ApoliceLifecycleResponse",
    "ApoliceLifecycleResult",
]

"""Monolith FactSheet Agent (engine v6_meritos camada 1, tier monolitico).

1 card por processo sintetizando PDF monolitico inteiro. Output cabe em
leads.dossier_artifacts com kind='monolith_factsheet'.

Substitui uso direto de autos_raw_excerpt no L2 — preserva RAG.
"""
from .agent import PROMPT_VERSION, classify_monolith_factsheet
from .schemas import (
    MonolithFactsheetCard,
    MonolithFactsheetRequest,
    MonolithFactsheetResponse,
    ProcessoContextMin,
)

__all__ = [
    "PROMPT_VERSION",
    "MonolithFactsheetCard",
    "MonolithFactsheetRequest",
    "MonolithFactsheetResponse",
    "ProcessoContextMin",
    "classify_monolith_factsheet",
]

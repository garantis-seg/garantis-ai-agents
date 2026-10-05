"""Processo Synthesis Agent (engine v6_meritos camada 2).

Sintetiza N L1 cards (mov_factsheet) + apolice context em 1 card de
processo. Full-RAG: SO cards estruturados, nunca raw. Output cabe em
leitura_conexos.dossier_artifacts com kind='processo_synthesis'.

Default model: `agent.DEFAULT_MODEL`.
"""
from .agent import classify_processo_synthesis
from .schemas import (
    ApoliceContextMin,
    MovFactSheetMin,
    ProcessoSynthesisCard,
    ProcessoSynthesisRequest,
    ProcessoSynthesisResponse,
)

__all__ = [
    "classify_processo_synthesis",
    "ApoliceContextMin",
    "MovFactSheetMin",
    "ProcessoSynthesisCard",
    "ProcessoSynthesisRequest",
    "ProcessoSynthesisResponse",
]

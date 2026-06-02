"""Processo Synthesis Agent (engine v6_meritos camada 2).

Sintetiza N L1 cards (mov_factsheet + day_factsheet) + apolice context em 1
card de processo. Full-RAG: SO cards estruturados, nunca raw. Output cabe em
leads.dossier_artifacts com kind='processo_synthesis'.

Default model: gemini-2.5-flash (mais robusto que Lite pra sintese).
"""
from .agent import classify_processo_synthesis
from .schemas import (
    ApoliceContextMin,
    DayFactSheetMin,
    MovFactSheetMin,
    ProcessoSynthesisCard,
    ProcessoSynthesisRequest,
    ProcessoSynthesisResponse,
)

__all__ = [
    "classify_processo_synthesis",
    "ApoliceContextMin",
    "DayFactSheetMin",
    "MovFactSheetMin",
    "ProcessoSynthesisCard",
    "ProcessoSynthesisRequest",
    "ProcessoSynthesisResponse",
]

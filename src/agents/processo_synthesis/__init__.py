"""Processo Synthesis Agent (engine v6_meritos camada 2).

Sintetiza N mov_factsheets de UM processo + apolice context em 7 campos
estruturados. Output cabe em leads.dossier_artifacts com kind='processo_synthesis'.

Default model: gemini-2.5-flash (mais robusto que Lite pra sintese).
"""

from .agent import classify_processo_synthesis
from .schemas import (
    ApoliceContextMin,
    AutosRawExcerpt,
    DocAutos,
    MovFactSheetMin,
    ProcessoSynthesisCard,
    ProcessoSynthesisRequest,
    ProcessoSynthesisResponse,
)

__all__ = [
    "classify_processo_synthesis",
    "ApoliceContextMin",
    "AutosRawExcerpt",
    "DocAutos",
    "MovFactSheetMin",
    "ProcessoSynthesisCard",
    "ProcessoSynthesisRequest",
    "ProcessoSynthesisResponse",
]

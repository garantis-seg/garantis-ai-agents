"""Mov FactSheet Agent (engine v6_meritos camada 1).

Extrai 13 campos estruturados de UMA movimentacao processual. Output cabe em
leads.dossier_artifacts com kind='mov_factsheet'.

Single-step Flash Lite call. Mais rico que mov_summarizer (kind='movimentacao'):
inclui evento_garantia, delta_risco, valores, peca_pivo, proximos_passos, etc.

Usado pela engine v6 como input da camada 2 (processo_synthesis).
"""

from .agent import classify_mov_factsheet
from .schemas import (
    DocAnexado,
    FallbackContext,
    MovFactSheetCard,
    MovFactSheetRequest,
    MovFactSheetResponse,
)

__all__ = [
    "classify_mov_factsheet",
    "DocAnexado",
    "FallbackContext",
    "MovFactSheetCard",
    "MovFactSheetRequest",
    "MovFactSheetResponse",
]

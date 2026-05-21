"""Day FactSheet Agent (engine v6_meritos camada 1, tier Degradado-Dia).

Sintetiza 1 dia inteiro de UM processo correlacionando movs + docs do
mesmo dia. Output cabe em leads.dossier_artifacts com kind='day_factsheet',
entity_id='{processo_numero}|{date}'.

Usado quando o tier do proc eh Degradado-Dia: docs com text_content existem
mas sem FK nativa doc<->mov (caso tipico Judit, jusbrasil sem id de anexo).
Tier eh regra de jogo, nao excecao — vide memory engine-v6-pipeline-quality-tiers.
"""

from .agent import classify_day_factsheet
from .schemas import (
    DayDocInput,
    DayFactsheetCard,
    DayFactsheetRequest,
    DayFactsheetResponse,
    DayMovInput,
    ProcessoContextMin,
)

__all__ = [
    "classify_day_factsheet",
    "DayDocInput",
    "DayFactsheetCard",
    "DayFactsheetRequest",
    "DayFactsheetResponse",
    "DayMovInput",
    "ProcessoContextMin",
]

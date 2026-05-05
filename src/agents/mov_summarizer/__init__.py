"""Mov Summarizer Agent.

Classifies and summarizes a single court movement (movimentação processual)
into a structured card schema (matches dossier_artifacts kind='movimentacao'
spec from prompts/risk-engine-v5-card-schemas.md).

Single-step Flash Lite call. Input: mov text + minimal processo context.
Output: tipo_canonico + flags + texto_resumo + decisao_de_merito (when applicable).
"""

from .agent import classify_mov
from .schemas import (
    MovSummarizerRequest,
    MovSummarizerResponse,
    MovCardSummary,
)

__all__ = [
    "classify_mov",
    "MovSummarizerRequest",
    "MovSummarizerResponse",
    "MovCardSummary",
]

"""Court State Classifier Agent (Onda 1 Fase B.3 — Fase 2 LLM upgrade).

Classifies the target state of a `leads.court_presentations` row given the
raw text of a movement (`leads.processos_movimentos.descricao`) and the
current_state of the presentation.

MVP regex-based classifier lives in
`execucao-fiscal/frontend-api/services/court_presentation_inference_service.py`
(`_classify_movement` + 5 regex tiers: ACCEPT/REJECT/CLOSED_SINISTRO/
CLOSED_LIBERADA/CLOSED_EXTINTO). This LLM agent is the Fase 2 upgrade —
gated by `USE_LLM_COURT_STATE_CLASSIFIER` env flag in the worker. Default
OFF.

Layer name for telemetry: `court_presentation_inference` (already exists
in garantis-shared 1.70.0).
"""

from .agent import classify_court_state
from .schemas import (
    CourtStateClassification,
    CourtStateClassifierRequest,
    CourtStateClassifierResponse,
)

__all__ = [
    "classify_court_state",
    "CourtStateClassification",
    "CourtStateClassifierRequest",
    "CourtStateClassifierResponse",
]

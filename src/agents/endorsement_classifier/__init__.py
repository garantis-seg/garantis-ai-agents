"""Endorsement Classifier Agent (Onda 2 Fase B.4 — Fase 2 LLM upgrade).

Classifies the type of an apolice endorsement (cancellation / extension /
sum_insured_change / other) given (a) the prior endorsement payload,
(b) the new observation payload, (c) the diff fields between them, and
(d) the raw observed_data text from the policy extraction.

MVP regex-based classifier lives in
`execucao-fiscal/frontend-api/services/apolice_derivation_service.py`. This
LLM agent is the Fase 2 upgrade — gated by `USE_LLM_ENDORSEMENT_CLASSIFIER`
env flag in the worker. Default OFF.

Layer name for telemetry: `apolice_endorsement_derivation`.
"""

from .agent import classify_endorsement
from .schemas import (
    EndorsementClassification,
    EndorsementClassifierRequest,
    EndorsementClassifierResponse,
)

__all__ = [
    "classify_endorsement",
    "EndorsementClassification",
    "EndorsementClassifierRequest",
    "EndorsementClassifierResponse",
]

"""Merito Synthesis Agent (engine v6_meritos camada 3 - OUTPUT PRIMARIO).

Agrega processo_syntheses de TODOS processos do merito + tomador + cda
+ snapshot anterior. Output: risco + justificativa + trajetoria
+ peca_pivo + proximos_passos.
(Jurisprudencia saiu do payload L3 na v2.2 — vive no L2, regras J/J.1/J.2.
Aiims saiu na v2.8, 2026-07-14 — teardown autos-wide, card AIIM removido.)

Persiste em monitoramento.risk_snapshots (via orchestrator no frontend-api).
"""

from .agent import classify_merito_synthesis
from .schemas import (
    CDACardMin,
    DecisaoAtual,
    EvidenceArtifact,
    MeritoSynthesisCard,
    MeritoSynthesisRequest,
    MeritoSynthesisResponse,
    PecaPivoMerito,
    PreviousSnapshot,
    ProcessoSynthesisMin,
    TomadorCardMin,
)

__all__ = [
    "classify_merito_synthesis",
    "CDACardMin",
    "DecisaoAtual",
    "EvidenceArtifact",
    "MeritoSynthesisCard",
    "MeritoSynthesisRequest",
    "MeritoSynthesisResponse",
    "PecaPivoMerito",
    "PreviousSnapshot",
    "ProcessoSynthesisMin",
    "TomadorCardMin",
]

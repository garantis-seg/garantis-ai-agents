"""Merito Synthesis Agent (engine v6_meritos camada 3 - OUTPUT PRIMARIO).

Agrega processo_syntheses de TODOS processos do merito + tomador + cda/aiim
+ jurisprudencia + snapshot anterior. Output: risco + justificativa + trajetoria
+ peca_pivo + proximos_passos.

Persiste em monitoramento.risk_snapshots (via orchestrator no frontend-api).
"""

from .agent import classify_merito_synthesis
from .schemas import (
    AIIMCardMin,
    CDACardMin,
    DecisaoAtual,
    EvidenceArtifact,
    JurisprudenciaMin,
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
    "AIIMCardMin",
    "CDACardMin",
    "DecisaoAtual",
    "EvidenceArtifact",
    "JurisprudenciaMin",
    "MeritoSynthesisCard",
    "MeritoSynthesisRequest",
    "MeritoSynthesisResponse",
    "PecaPivoMerito",
    "PreviousSnapshot",
    "ProcessoSynthesisMin",
    "TomadorCardMin",
]

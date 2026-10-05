"""Merito Synthesis Agent (engine v6_meritos camada 3 - OUTPUT PRIMARIO).

Agrega processo_syntheses de TODOS processos do merito + tomador + cda (o
`previous_snapshot` do request e aceito por compat e nao entra no prompt).
Output: risco + justificativa + trajetoria + peca_pivo + proximos_passos.
(Jurisprudencia nao entra no L3: vive no L2, regras J/J.1/J.2.)

Persiste em leitura_conexos.risk_snapshots (via o materializer L3 do garantis-shared).
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

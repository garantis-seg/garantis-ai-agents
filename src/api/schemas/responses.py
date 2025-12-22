"""
Response schemas para a API.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from ...scoring.types import ScoreBreakdown, CalculatedTemporalData, TimingBase


class AnalyzeResponse(BaseModel):
    """Response da análise de timing."""

    # Identificação
    processo_numero: str

    # Resultados de alto nível (V3)
    timing_base: TimingBase = Field(
        description="Classificação de timing: AGORA_CONSTITUICAO, AGORA_SUBSTITUICAO, ACOMPANHAR, PASSOU"
    )
    score_final: int = Field(description="Score final (0-10)")

    # Detalhamento
    score_breakdown: ScoreBreakdown = Field(description="Detalhamento do cálculo do score")
    llm_response: Dict[str, Any] = Field(description="Resposta completa do LLM (5 nodes)")
    temporal_data: Optional[CalculatedTemporalData] = Field(
        default=None,
        description="Dados temporais calculados"
    )

    # Metadata
    tokens_used: int = Field(description="Total de tokens usados")
    cost_usd: float = Field(description="Custo em USD")
    model: str = Field(description="Modelo usado")
    prompt_version: str = Field(description="Versão do prompt usada")
    analyzed_at: datetime = Field(description="Timestamp da análise")
    cached: bool = Field(default=False, description="Se a resposta veio do cache")

    # Campos legados (compatibilidade com gemini-timing)
    diagnostico_timing: str = Field(
        description="Timing simplificado: AGORA, PASSOU, ACOMPANHAR (legado)"
    )
    score_oportunidade: float = Field(description="Score como float (legado)")
    justificativa_curta: str = Field(description="Justificativa curta (legado)")
    recomendacao_final: str = Field(description="Recomendação final (legado)")


class AnalyzeBatchItemResult(BaseModel):
    """Resultado de um item do batch."""
    processo_numero: str
    success: bool
    timing_base: Optional[TimingBase] = None
    score_final: Optional[int] = None
    error: Optional[str] = None


class AnalyzeBatchResponse(BaseModel):
    """Response da análise em lote."""
    results: List[AnalyzeBatchItemResult]
    total: int
    success_count: int
    error_count: int
    total_tokens: int
    total_cost_usd: float


class PromptsResponse(BaseModel):
    """Response da listagem de prompts."""
    agent: str
    active_version: str
    versions: List[Dict[str, Any]]


class HealthResponse(BaseModel):
    """Response do health check."""
    status: str
    version: str
    model_default: str
    prompt_default: str

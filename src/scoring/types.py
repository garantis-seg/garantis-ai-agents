"""
Tipos para o sistema de scoring.
"""

from enum import Enum
from typing import List, Optional
from pydantic import BaseModel


class TimingBase(str, Enum):
    """Classificação base de timing."""
    AGORA_CONSTITUICAO = "AGORA_CONSTITUICAO"
    AGORA_SUBSTITUICAO = "AGORA_SUBSTITUICAO"
    ACOMPANHAR = "ACOMPANHAR"
    PASSOU = "PASSOU"


class CalculatedTemporalData(BaseModel):
    """Dados temporais calculados a partir dos marcos."""
    dias_desde_marco_primario: int
    dias_desde_marco_mais_recente: int


class ScoreBreakdown(BaseModel):
    """Detalhamento completo do cálculo de score."""
    timing_base: TimingBase
    base: int
    penalties: int
    penalty_details: List[str]
    bonus: int
    bonus_details: List[str]
    grave_multiplier: float
    final: int


class ScoringResult(BaseModel):
    """Resultado completo do cálculo de score."""
    score_breakdown: ScoreBreakdown
    temporal_data: Optional[CalculatedTemporalData] = None

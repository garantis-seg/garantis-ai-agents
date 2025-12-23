"""
Calculador de score V3.
Port de poc-prompt-benchmark/src/lib/scoring.ts para Python.
"""

from dataclasses import dataclass
from datetime import date
from typing import List, Optional

from ..agents.timing_analysis.schemas import (
    LLMResponseV3,
    TipoGarantia,
    GarantiaAnswer,
    InferenceBasis,
)
from .types import (
    TimingBase,
    ScoreBreakdown,
    CalculatedTemporalData,
    ScoringResult,
)
from .temporal import calculate_temporal_data


# ========== Constantes ==========

BASE_SCORES = {
    TimingBase.AGORA_CONSTITUICAO: 9,
    TimingBase.AGORA_SUBSTITUICAO: 9,
    TimingBase.ACOMPANHAR: 6,
    TimingBase.PASSOU: 2,
}

TIPOS_GARANTIA_SUBSTITUIVEIS = [
    TipoGarantia.DEPOSITO_JUDICIAL,
    TipoGarantia.PENHORA_DINHEIRO,
    TipoGarantia.PENHORA_BENS_MOVEIS,
    TipoGarantia.PENHORA_BENS_IMOVEIS,
    TipoGarantia.FIANCA_BANCARIA,
    TipoGarantia.CAUCAO_REAL,
]


# ========== Dataclasses para resultados intermediários ==========

@dataclass
class ScoringPathResult:
    """Resultado intermediário do cálculo de scoring para um caminho (5A ou 5B)."""
    timing: TimingBase
    penalties: List[str]
    bonuses: List[str]
    grave_multiplier: float


# ========== Scoring 5B (Constituição) ==========

def calculate_5b_scoring(
    response: LLMResponseV3,
    temporal: CalculatedTemporalData,
) -> ScoringPathResult:
    """
    Calcula scoring para caminho 5B (constituição de nova garantia).
    Baseado na tabela de cenários definida.

    Args:
        response: Resposta do LLM
        temporal: Dados temporais calculados

    Returns:
        Resultado do scoring com timing, penalties e bonuses.
    """
    details = response.node_5_analise_especifica.details_5b if response.node_5_analise_especifica else None
    marcos = response.node_3_marcos_temporais
    variaveis = response.variaveis_llm

    penalties: List[str] = []
    bonuses: List[str] = []
    timing = TimingBase.ACOMPANHAR
    grave_multiplier = 1.0

    if not details or not marcos:
        return ScoringPathResult(
            timing=TimingBase.PASSOU,
            penalties=[],
            bonuses=[],
            grave_multiplier=1.0,
        )

    # Processo encerrado → PASSOU
    if details.processo_encerrado:
        return ScoringPathResult(
            timing=TimingBase.PASSOU,
            penalties=[],
            bonuses=[],
            grave_multiplier=1.0,
        )

    dias = temporal.dias_desde_marco_mais_recente
    ameaca = details.ameaca_constricao_iminente
    executado_ativo = details.executado_ativo

    # ========== Tabela de Decisão 5B ==========

    if dias < 15:
        # Marco muito recente
        timing = TimingBase.AGORA_CONSTITUICAO
        bonuses.append("marco_recente_15_dias")
        if ameaca:
            bonuses.append("ameaca_constricao_iminente")

    elif dias < 60:
        # 15-60 dias
        if ameaca:
            timing = TimingBase.AGORA_CONSTITUICAO
            bonuses.append("ameaca_constricao_iminente")
        else:
            timing = TimingBase.AGORA_CONSTITUICAO  # Ainda dentro da janela

    elif dias < 90:
        # 60-90 dias
        if ameaca:
            timing = TimingBase.AGORA_CONSTITUICAO
            bonuses.append("ameaca_constricao_iminente")
        else:
            timing = TimingBase.ACOMPANHAR
            penalties.append("marco_acima_60_dias")

    else:
        # > 90 dias
        if ameaca:
            timing = TimingBase.AGORA_CONSTITUICAO
            bonuses.append("ameaca_constricao_iminente")
            penalties.append("marco_acima_90_dias")
        else:
            timing = TimingBase.ACOMPANHAR
            penalties.append("marco_acima_90_dias")
            if dias > 180:
                penalties.append("marco_acima_180_dias")

    # ========== Contextos Especiais ==========

    contextos = marcos.contextos_especiais
    tem_contexto_especial = (
        contextos.recuperacao_judicial.detected
        or contextos.falencia_devedor.detected
        or contextos.acordo_em_negociacao.detected
        or contextos.processo_suspenso.detected
    )

    if tem_contexto_especial:
        penalties.append("contexto_especial_presente")
        # Rebaixar AGORA para ACOMPANHAR
        if timing == TimingBase.AGORA_CONSTITUICAO:
            timing = TimingBase.ACOMPANHAR

    # ========== Passividade Histórica ==========

    if temporal.dias_desde_marco_primario > 365 and variaveis.executado_demonstrou_passividade:
        grave_multiplier = 0.75
        penalties.append("passividade_historica_cliente")

    # ========== Bônus Executado Ativo ==========

    if executado_ativo:
        bonuses.append("executado_ativo")

    return ScoringPathResult(
        timing=timing,
        penalties=penalties,
        bonuses=bonuses,
        grave_multiplier=grave_multiplier,
    )


# ========== Scoring 5A (Substituição) ==========

def calculate_5a_scoring(
    response: LLMResponseV3,
    temporal: CalculatedTemporalData,
) -> ScoringPathResult:
    """
    Calcula scoring para caminho 5A (substituição de garantia existente).

    Args:
        response: Resposta do LLM
        temporal: Dados temporais calculados

    Returns:
        Resultado do scoring com timing, penalties e bonuses.
    """
    details = response.node_5_analise_especifica.details_5a if response.node_5_analise_especifica else None
    marcos = response.node_3_marcos_temporais
    variaveis = response.variaveis_llm
    node4 = response.node_4_garantia_existente

    penalties: List[str] = []
    bonuses: List[str] = []
    timing = TimingBase.ACOMPANHAR
    grave_multiplier = 1.0

    if not details or not marcos:
        return ScoringPathResult(
            timing=TimingBase.PASSOU,
            penalties=[],
            bonuses=[],
            grave_multiplier=1.0,
        )

    tipo_garantia = TipoGarantia(details.tipo_garantia) if isinstance(details.tipo_garantia, str) else details.tipo_garantia
    garantia_onerosa = details.garantia_onerosa

    # ========== Tabela de Decisão 5A ==========

    # Já é seguro garantia → PASSOU
    if tipo_garantia == TipoGarantia.SEGURO_GARANTIA:
        return ScoringPathResult(
            timing=TimingBase.PASSOU,
            penalties=[],
            bonuses=[],
            grave_multiplier=1.0,
        )

    # Garantia onerosa + tipo substituível → AGORA
    if garantia_onerosa and tipo_garantia in TIPOS_GARANTIA_SUBSTITUIVEIS:
        timing = TimingBase.AGORA_SUBSTITUICAO
        bonuses.append("evidencia_direta_garantia_onerosa")

    # Tipo indefinido → ACOMPANHAR (verificar com cliente)
    elif tipo_garantia == TipoGarantia.INDEFINIDO:
        timing = TimingBase.ACOMPANHAR
        penalties.append("tipo_garantia_desconhecido")

    # Outros casos
    else:
        timing = TimingBase.ACOMPANHAR

    # ========== Incerteza sobre Garantia Existente ==========

    if node4:
        # Converter para enum se necessário
        answer = GarantiaAnswer(node4.answer) if isinstance(node4.answer, str) else node4.answer
        inference_basis = InferenceBasis(node4.inference_basis) if isinstance(node4.inference_basis, str) else node4.inference_basis

        # Penalizar quando a garantia não é confirmada com certeza
        if answer == GarantiaAnswer.PROVAVELMENTE_SIM:
            penalties.append("garantia_provavel_nao_confirmada")
        elif answer == GarantiaAnswer.INCERTO:
            penalties.append("garantia_incerta")

        # Penalizar inferência por silêncio
        if inference_basis == InferenceBasis.SILENCIO or variaveis.garantia_inferida_silencio:
            penalties.append("garantia_inferida_silencio")

    # ========== Penalidades Temporais ==========

    dias = temporal.dias_desde_marco_mais_recente
    if dias > 90:
        penalties.append("marco_acima_90_dias")
    if dias > 180:
        penalties.append("marco_acima_180_dias")

    # ========== Contextos Especiais ==========

    contextos = marcos.contextos_especiais
    tem_contexto_especial = (
        contextos.recuperacao_judicial.detected
        or contextos.falencia_devedor.detected
        or contextos.acordo_em_negociacao.detected
        or contextos.processo_suspenso.detected
    )

    if tem_contexto_especial:
        penalties.append("contexto_especial_presente")
        if timing == TimingBase.AGORA_SUBSTITUICAO:
            timing = TimingBase.ACOMPANHAR

    # ========== Passividade Histórica ==========

    if temporal.dias_desde_marco_primario > 365 and variaveis.executado_demonstrou_passividade:
        grave_multiplier = 0.75
        penalties.append("passividade_historica_cliente")

    return ScoringPathResult(
        timing=timing,
        penalties=penalties,
        bonuses=bonuses,
        grave_multiplier=grave_multiplier,
    )


# ========== Cálculo Principal V3 ==========

def calculate_score_v3(
    response: LLMResponseV3,
    today: Optional[date] = None,
) -> Optional[ScoringResult]:
    """
    Calcula score completo para resposta V3.

    Args:
        response: Resposta do LLM (V3)
        today: Data de referência (default: hoje)

    Returns:
        Resultado do scoring ou None se não for possível calcular.
    """
    today = today or date.today()

    # Nó 1 = NÃO → PASSOU
    if response.node_1_plausibilidade.answer == "NÃO":
        return ScoringResult(
            score_breakdown=ScoreBreakdown(
                timing_base=TimingBase.PASSOU,
                base=BASE_SCORES[TimingBase.PASSOU],
                penalties=0,
                penalty_details=[],
                bonus=0,
                bonus_details=[],
                grave_multiplier=1.0,
                final=BASE_SCORES[TimingBase.PASSOU],
            ),
            temporal_data=None,
        )

    # Nó 2 = NÃO → ACOMPANHAR
    if response.node_2_materializacao and response.node_2_materializacao.answer == "NÃO":
        return ScoringResult(
            score_breakdown=ScoreBreakdown(
                timing_base=TimingBase.ACOMPANHAR,
                base=BASE_SCORES[TimingBase.ACOMPANHAR],
                penalties=0,
                penalty_details=[],
                bonus=0,
                bonus_details=[],
                grave_multiplier=1.0,
                final=BASE_SCORES[TimingBase.ACOMPANHAR],
            ),
            temporal_data=None,
        )

    # Calcular dados temporais
    temporal_data = calculate_temporal_data(response, today)
    if not temporal_data:
        # Fallback: sem dados temporais válidos → ACOMPANHAR
        return ScoringResult(
            score_breakdown=ScoreBreakdown(
                timing_base=TimingBase.ACOMPANHAR,
                base=BASE_SCORES[TimingBase.ACOMPANHAR],
                penalties=0,
                penalty_details=["Sem dados temporais válidos"],
                bonus=0,
                bonus_details=[],
                grave_multiplier=1.0,
                final=BASE_SCORES[TimingBase.ACOMPANHAR],
            ),
            temporal_data=None,
        )

    # Determinar caminho (5A ou 5B)
    if not response.node_5_analise_especifica:
        # Fallback: sem análise específica (node 5) → ACOMPANHAR
        return ScoringResult(
            score_breakdown=ScoreBreakdown(
                timing_base=TimingBase.ACOMPANHAR,
                base=BASE_SCORES[TimingBase.ACOMPANHAR],
                penalties=0,
                penalty_details=["Sem análise específica (node 5)"],
                bonus=0,
                bonus_details=[],
                grave_multiplier=1.0,
                final=BASE_SCORES[TimingBase.ACOMPANHAR],
            ),
            temporal_data=temporal_data,
        )

    type_active = response.node_5_analise_especifica.type_active

    if type_active == "5A_SUBSTITUICAO":
        scoring_result = calculate_5a_scoring(response, temporal_data)
    elif type_active == "5B_CONSTITUICAO":
        scoring_result = calculate_5b_scoring(response, temporal_data)
    else:
        # Fallback: type_active inválido → ACOMPANHAR
        return ScoringResult(
            score_breakdown=ScoreBreakdown(
                timing_base=TimingBase.ACOMPANHAR,
                base=BASE_SCORES[TimingBase.ACOMPANHAR],
                penalties=0,
                penalty_details=[f"Tipo de análise inválido: {type_active}"],
                bonus=0,
                bonus_details=[],
                grave_multiplier=1.0,
                final=BASE_SCORES[TimingBase.ACOMPANHAR],
            ),
            temporal_data=temporal_data,
        )

    # Calcular score final
    base = BASE_SCORES[scoring_result.timing]
    penalty_count = len(scoring_result.penalties)
    bonus_count = len(scoring_result.bonuses)

    intermediate = max(0, min(10, base - penalty_count + bonus_count))
    final = round(intermediate * scoring_result.grave_multiplier)

    return ScoringResult(
        score_breakdown=ScoreBreakdown(
            timing_base=scoring_result.timing,
            base=base,
            penalties=-penalty_count,
            penalty_details=scoring_result.penalties,
            bonus=bonus_count,
            bonus_details=scoring_result.bonuses,
            grave_multiplier=scoring_result.grave_multiplier,
            final=final,
        ),
        temporal_data=temporal_data,
    )


def format_score_breakdown(breakdown: ScoreBreakdown) -> str:
    """
    Formata o breakdown do score para exibição.

    Args:
        breakdown: Breakdown do score

    Returns:
        String formatada.
    """
    parts = [f"Base: {breakdown.base}"]

    if breakdown.penalties != 0:
        parts.append(f"Penalidades: {breakdown.penalties}")

    if breakdown.bonus != 0:
        parts.append(f"Bônus: +{breakdown.bonus}")

    if breakdown.grave_multiplier != 1.0:
        parts.append(f"Grave: ×{breakdown.grave_multiplier}")

    parts.append(f"Final: {breakdown.final}")

    return " | ".join(parts)

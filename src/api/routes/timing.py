"""
Endpoints para análise de timing.
"""

import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException

from ...agents.timing_analysis.agent import analyze_timing
from ...agents.timing_analysis.schemas import LLMResponseV3
from ...models.config import calculate_cost, DEFAULT_MODEL
from ...scoring.calculator import calculate_score_v3
from ...scoring.types import TimingBase
from ..schemas.requests import AnalyzeRequest, AnalyzeBatchRequest, CaseData, Movement
from ..schemas.responses import (
    AnalyzeResponse,
    AnalyzeBatchItemResult,
    AnalyzeBatchResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/timing", tags=["timing"])

DEFAULT_PROMPT_VERSION = os.getenv("DEFAULT_PROMPT_VERSION", "v3")


def format_case_data(case_data: CaseData, movements: List[Movement]) -> str:
    """
    Formata dados do processo para o prompt.

    Args:
        case_data: Dados do processo
        movements: Lista de movimentações

    Returns:
        String formatada para inserir no prompt.
    """
    # Formatar polos
    def format_polo(polo: Any) -> str:
        if isinstance(polo, list):
            lines = []
            for item in polo:
                if isinstance(item, dict):
                    nome = item.get("nome", "")
                    tipo = item.get("tipo", "")
                    lines.append(f"- {tipo}: {nome}")
                else:
                    lines.append(f"- {item}")
            return "\n".join(lines) if lines else "Não informado"
        return str(polo) if polo else "Não informado"

    # Formatar valor
    case_value_str = "Não informado"
    if case_data.case_value:
        try:
            case_value_str = f"R$ {float(case_data.case_value):,.2f}"
        except (ValueError, TypeError):
            case_value_str = str(case_data.case_value)

    # Montar dados do processo
    process_text = f"""
## DADOS DO PROCESSO

**Número do Processo:** {case_data.processo_numero}
**Tribunal/Foro:** {case_data.foro or 'N/A'}
**Classe:** {case_data.classe or 'N/A'}
**Assunto:** {case_data.assunto or 'N/A'}
**Valor da Ação:** {case_value_str}

### POLO ATIVO (Exequente/Autor):
{format_polo(case_data.polo_ativo)}

### POLO PASSIVO (Executado/Réu):
{format_polo(case_data.polo_passivo)}

### ADVOGADOS:
- Executado: {case_data.executado_advogado or 'Não informado'}
- Exequente: {case_data.exequente_advogado_nome or 'Não informado'}

### MOVIMENTAÇÕES ({len(movements)} registros):
"""

    # Adicionar movimentações
    for mov in movements:
        process_text += f"[{mov.data_movimento}] {mov.descricao}\n"

    return process_text


def timing_base_to_legacy(timing: TimingBase) -> str:
    """Converte TimingBase para formato legado."""
    if timing in (TimingBase.AGORA_CONSTITUICAO, TimingBase.AGORA_SUBSTITUICAO):
        return "AGORA"
    return timing.value


def generate_justificativa(llm_response: LLMResponseV3) -> str:
    """Gera justificativa curta a partir da resposta do LLM."""
    parts = []

    if llm_response.node_1_plausibilidade:
        parts.append(llm_response.node_1_plausibilidade.reasoning[:100])

    if llm_response.node_5_analise_especifica:
        if llm_response.node_5_analise_especifica.details_5a:
            parts.append(llm_response.node_5_analise_especifica.details_5a.reasoning[:100])
        elif llm_response.node_5_analise_especifica.details_5b:
            parts.append(llm_response.node_5_analise_especifica.details_5b.reasoning[:100])

    return " | ".join(parts)[:300] if parts else "Análise realizada via V3"


def generate_recomendacao(timing: TimingBase) -> str:
    """Gera recomendação final baseada no timing."""
    if timing == TimingBase.AGORA_CONSTITUICAO:
        return "Oferecer seguro garantia para constituição de garantia"
    elif timing == TimingBase.AGORA_SUBSTITUICAO:
        return "Oferecer seguro garantia para substituição de garantia existente"
    elif timing == TimingBase.ACOMPANHAR:
        return "Monitorar processo para oportunidades futuras"
    else:
        return "Encerrar acompanhamento - timing passou"


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_process(request: AnalyzeRequest):
    """
    Analisa um processo judicial para timing de seguro garantia.

    Flow:
    1. Formata dados do processo
    2. Chama o agente com o modelo/prompt especificado
    3. Calcula score usando lógica de backend
    4. Retorna resposta combinada (V3 + legado)
    """
    model = request.model or DEFAULT_MODEL
    prompt_version = request.prompt_version or DEFAULT_PROMPT_VERSION

    # Formatar dados do processo
    process_data = format_case_data(request.case_data, request.movements)

    try:
        # Chamar agente
        result = await analyze_timing(
            process_data=process_data,
            model=model,
            prompt_version=prompt_version,
        )

        # Verificar se temos resposta válida
        if not result.get("llm_response"):
            raise HTTPException(
                status_code=500,
                detail=f"Agente não produziu resposta estruturada: {result.get('raw_response', '')[:200]}"
            )

        llm_response: LLMResponseV3 = result["llm_response"]

        # Calcular score
        scoring_result = calculate_score_v3(llm_response)
        if not scoring_result:
            raise HTTPException(
                status_code=500,
                detail="Falha no cálculo de score"
            )

        # Calcular custo
        usage = result.get("usage", {})
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("candidates_tokens", 0)
        total_tokens = usage.get("total_tokens", input_tokens + output_tokens)
        cost = calculate_cost(model, input_tokens, output_tokens)

        # Montar resposta
        return AnalyzeResponse(
            processo_numero=request.case_data.processo_numero,
            timing_base=scoring_result.score_breakdown.timing_base,
            score_final=scoring_result.score_breakdown.final,
            score_breakdown=scoring_result.score_breakdown,
            llm_response=llm_response.model_dump(),
            temporal_data=scoring_result.temporal_data,
            tokens_used=total_tokens,
            cost_usd=cost,
            model=model,
            prompt_version=prompt_version,
            analyzed_at=datetime.utcnow(),
            cached=False,
            # Campos legados
            diagnostico_timing=timing_base_to_legacy(scoring_result.score_breakdown.timing_base),
            score_oportunidade=float(scoring_result.score_breakdown.final),
            justificativa_curta=generate_justificativa(llm_response),
            recomendacao_final=generate_recomendacao(scoring_result.score_breakdown.timing_base),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Erro na análise do processo {request.case_data.processo_numero}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/analyze-batch", response_model=AnalyzeBatchResponse)
async def analyze_batch(request: AnalyzeBatchRequest):
    """
    Analisa múltiplos processos em lote.

    Processa cada item sequencialmente para evitar rate limits.
    """
    results: List[AnalyzeBatchItemResult] = []
    total_tokens = 0
    total_cost = 0.0
    success_count = 0
    error_count = 0

    model = request.model or DEFAULT_MODEL
    prompt_version = request.prompt_version or DEFAULT_PROMPT_VERSION

    for item in request.items:
        # Usar modelo/prompt do batch se não especificado no item
        item.model = item.model or model
        item.prompt_version = item.prompt_version or prompt_version

        try:
            response = await analyze_process(item)
            results.append(
                AnalyzeBatchItemResult(
                    processo_numero=item.case_data.processo_numero,
                    success=True,
                    timing_base=response.timing_base,
                    score_final=response.score_final,
                )
            )
            total_tokens += response.tokens_used
            total_cost += response.cost_usd
            success_count += 1

        except Exception as e:
            results.append(
                AnalyzeBatchItemResult(
                    processo_numero=item.case_data.processo_numero,
                    success=False,
                    error=str(e),
                )
            )
            error_count += 1

    return AnalyzeBatchResponse(
        results=results,
        total=len(request.items),
        success_count=success_count,
        error_count=error_count,
        total_tokens=total_tokens,
        total_cost_usd=total_cost,
    )

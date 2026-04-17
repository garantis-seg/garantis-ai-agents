"""Pydantic schemas for risk classification agent."""

from typing import Literal, Optional
from pydantic import BaseModel, Field


class ProcessSummaryResult(BaseModel):
    """Structured summary of process facts extracted from movements."""

    embargos_status: Literal[
        "nao_opostos", "pendentes", "procedentes", "improcedentes", "parcialmente_procedentes"
    ] = Field(description="Status dos embargos/impugnação")
    embargos_instancia: Optional[Literal["1a", "2a", "superior"]] = Field(
        default=None, description="Instância atual dos embargos"
    )
    embargos_recurso_pendente: bool = Field(
        default=False, description="Se há recurso pendente nos embargos"
    )
    embargos_resultado_2a_instancia: Optional[Literal[
        "mantido_desfavoravel", "reformado_favoravel", "pendente"
    ]] = Field(default=None, description="Resultado em 2ª instância")
    acao_anulatoria_status: Literal[
        "inexistente", "sem_decisao", "favoravel", "desfavoravel"
    ] = Field(default="inexistente", description="Status da ação anulatória/MS paralela")
    acao_anulatoria_recurso_pendente: bool = Field(
        default=False, description="Se há recurso pendente na ação anulatória"
    )
    transito_em_julgado: bool = Field(
        default=False, description="Se houve trânsito em julgado"
    )
    transito_favoravel_tomador: Optional[bool] = Field(
        default=None, description="Se o trânsito foi favorável ao Tomador"
    )
    acordo_parcelamento: Literal[
        "inexistente", "vigente", "descumprido"
    ] = Field(default="inexistente", description="Status de acordo/parcelamento")
    processo_suspenso: bool = Field(
        default=False, description="Se o processo está suspenso"
    )
    motivo_suspensao: Optional[str] = Field(
        default=None, description="Motivo da suspensão"
    )
    intimacao_pagamento: bool = Field(
        default=False, description="Se houve intimação para pagamento"
    )
    determinacao_pagamento_seguradora: bool = Field(
        default=False, description="Se há decisão determinando pagamento pela seguradora"
    )
    resumo_situacao: str = Field(
        description="1-2 frases descrevendo a situação processual atual"
    )


class RiskClassificationResult(BaseModel):
    """Structured output from the risk classifier LLM."""

    risco: Literal["Baixo", "Medio", "Alto", "Altissimo"] = Field(
        description="Nivel de risco de acionamento da apolice de seguro garantia"
    )
    justificativa: str = Field(
        description=(
            "Justificativa do risco em 2-3 frases, citando o criterio "
            "especifico da matriz de risco que se aplica"
        )
    )
    recomendacao: str = Field(
        description="Recomendacao pratica de acao para a equipe comercial/P&P da seguradora"
    )
    andamentos_resumo: str = Field(
        description=(
            "Resumo dos andamentos processuais relevantes em ordem cronologica, "
            "3-5 bullet points com datas"
        )
    )


class RiskClassificationRequest(BaseModel):
    """Request body for risk classification endpoint."""

    processo_data: dict = Field(description="Process metadata: nr_processo, materia, fase, etc.")
    movimentacoes: list[dict] = Field(description="List of movements from Escavador API")
    cluster_processos: list[dict] | None = Field(
        default=None,
        description="Related processes with their movements for cluster context",
    )
    provider: str | None = Field(default=None, description="LLM provider override")
    model: str | None = Field(default=None, description="Model override")


class RiskClassificationResponse(BaseModel):
    """Response from risk classification endpoint."""

    classification: RiskClassificationResult
    usage: dict = Field(default_factory=dict)

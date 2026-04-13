"""Pydantic schemas for risk classification agent."""

from typing import Literal
from pydantic import BaseModel, Field


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
    provider: str | None = Field(default=None, description="LLM provider override")
    model: str | None = Field(default=None, description="Model override")


class RiskClassificationResponse(BaseModel):
    """Response from risk classification endpoint."""

    classification: RiskClassificationResult
    usage: dict = Field(default_factory=dict)

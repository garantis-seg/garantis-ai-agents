"""Schemas do AUDITOR DE EVIDENCIAS (C4).

O auditor responde UMA pergunta por evidencia, que a maquina nao sabe responder:
o trecho citado — que o codigo ja confirmou existir no documento — **sustenta**
o valor da celula?

A verificacao de EXISTENCIA e deterministica e roda antes (shared:
`evidencias.verificar_evidencias`). O que sobra e semantico: o trecho fala do
tributo certo? do periodo certo? o numero citado e o principal ou o consolidado?
e a base de calculo em vez do credito tributario? Isso e leitura, nao string
matching.

Veredicto por celula: `{celula_id, aprovada, motivo}`. Uma reprovada derruba a
rodada inteira — e o `motivo` volta ao calculador como instrucao de correcao,
entao ele precisa dizer o que fazer.
"""

from typing import Any, Optional

from pydantic import BaseModel, Field


class Veredicto(BaseModel):
    """O julgamento de UMA evidencia."""

    celula_id: str = Field(description="Celula julgada.")
    aprovada: bool = Field(
        description="True so se o trecho SUSTENTA o valor. Na duvida, False."
    )
    motivo: str = Field(
        default="",
        description=(
            "Obrigatorio quando aprovada=false: o que esta errado E o que o "
            "calculador deve fazer. Volta a ele como instrucao de correcao."
        ),
    )

    model_config = {"extra": "ignore"}


class AuditarEvidenciasRequest(BaseModel):
    """Request do POST /calculo-ficha/auditar-evidencias."""

    celulas: list[dict[str, Any]] = Field(
        description="Grafo montado pelo calculador (dados e formulas)."
    )
    evidencias: list[dict[str, Any]] = Field(
        description="Evidencias a julgar (ja verificadas como EXISTENTES pelo codigo)."
    )
    documentos: dict[str, Any] = Field(
        default_factory=dict,
        description="documento -> texto, ou documento -> {pagina: texto}.",
    )
    provider: Optional[str] = None
    model: Optional[str] = Field(
        default=None,
        description=(
            "Modelo do auditor. Precisa ser DIFERENTE do calculador: dois erros "
            "correlacionados do mesmo modelo se confirmariam mutuamente."
        ),
    )

    model_config = {"extra": "ignore"}


class AuditarEvidenciasResponse(BaseModel):
    """Response do POST /calculo-ficha/auditar-evidencias.

    Envelope da casa: {success, ..., model, cost_usd}. Em falha,
    `success=false` + error — e o harness trata como rejeicao da rodada
    (falha do auditor NUNCA vira aprovacao por omissao).
    """

    success: bool
    veredictos: list[dict[str, Any]] = Field(default_factory=list)
    model: str = ""
    cost_usd: float = 0.0
    error: Optional[str] = None


__all__ = [
    "AuditarEvidenciasRequest",
    "AuditarEvidenciasResponse",
    "Veredicto",
]

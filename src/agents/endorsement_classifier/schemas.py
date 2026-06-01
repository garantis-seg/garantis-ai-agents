"""Pydantic schemas for endorsement_classifier agent."""

from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


# ── Output schema ────────────────────────────────────────────────────────


class EndorsementClassification(BaseModel):
    """Classification output for one endorsement event.

    Output do LLM. Worker `apolice_derivation_service` persiste em
    `leads.endorsements.type` + `payload` (mantém merge logic).
    """

    endorsement_type: Literal[
        "cancellation",
        "extension",
        "sum_insured_change",
        "other",
    ] = Field(
        description=(
            "Tipo derivado do endosso. "
            "cancellation = apolice cancelada (cessação do risco, extinção). "
            "extension = prorrogação de prazo / nova vigência. "
            "sum_insured_change = alteração de IS / limite máximo / garantia. "
            "other = outro tipo não enquadrado acima (alteração de tomador, beneficiário, etc.)."
        ),
    )
    confidence: float = Field(
        default=0.5,
        description=(
            "Confiança na classificação (0.0-1.0). "
            "Alta (>=0.8) quando há keyword textual explícita + diff coerente. "
            "Baixa (<0.5) quando só diff numérico sem texto justificando."
        ),
    )
    reasoning: Optional[str] = Field(
        default=None,
        description=(
            "Justificativa curta (até 300 chars). Cite o trecho de "
            "objetoSegurado e os campos que mudaram. Útil pra audit."
        ),
    )


# ── Request / Response wrappers ──────────────────────────────────────────


class EndorsementClassifierRequest(BaseModel):
    """Input pro classifier: prior+new payload + diff + observed_data raw."""

    objeto_segurado: Optional[str] = Field(
        default=None,
        description=(
            "Texto livre do objeto segurado / descrição do endosso "
            "(observed_data.step2_objetoSegurado ou objeto_segurado). "
            "Costuma carregar a keyword explícita ('FICA CANCELADA', "
            "'PRORROGAÇÃO DE PRAZO', 'ALTERAÇÃO DE IS', etc.)."
        ),
    )
    prior_payload: Optional[dict[str, Any]] = Field(
        default=None,
        description=(
            "Payload do último endorsement antes deste evento. "
            "Campos esperados: current_sum_insured, termination_date, "
            "accumulated_premium, policyholder_cnpj, policyholder_name. "
            "Null se é a primeira observation (sem prior — só issuance)."
        ),
    )
    new_payload: dict[str, Any] = Field(
        description=(
            "Payload da nova observation (campos mutáveis extraídos)."
        ),
    )
    diff_fields: list[str] = Field(
        default_factory=list,
        description=(
            "Lista de nomes de campos que mudaram entre prior_payload "
            "e new_payload. Subset de: current_sum_insured, termination_date, "
            "accumulated_premium, policyholder_cnpj, policyholder_name."
        ),
    )
    apolice_numero: Optional[str] = Field(
        default=None,
        description="Número da apólice (contexto, NÃO é classificado).",
    )
    model: Optional[str] = Field(
        default=None,
        description="Override do modelo (default: gemini-2.5-flash-lite via env).",
    )
    provider: Optional[str] = Field(
        default=None,
        description="Override do provider (default: gemini).",
    )


class EndorsementClassifierResponse(BaseModel):
    """Wrapped output do endpoint."""

    classification: EndorsementClassification
    raw_response: Optional[str] = None
    prompt_version: Optional[str] = None
    usage: Optional[dict[str, Any]] = None

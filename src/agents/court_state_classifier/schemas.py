"""Pydantic schemas for court_state_classifier agent."""

from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


# ── Output schema ────────────────────────────────────────────────────────


class CourtStateClassification(BaseModel):
    """Classification output for one court_presentation state transition.

    Output do LLM. Worker `court_presentation_inference_service` persiste
    em `leads.court_presentations.current_state` + append em
    `state_history` (mantém merge logic + trigger fn_court_pres_append_*).
    """

    new_state: Literal[
        "offered",
        "presumed_accepted",
        "accepted",
        "rejected",
        "replaced",
        "closed",
    ] = Field(
        description=(
            "Estado-alvo inferido a partir do texto do movimento. "
            "offered = apólice oferecida (estado inicial). "
            "presumed_accepted = aceite presumido (sem manifestação contrária). "
            "accepted = juiz acolheu/deferiu/homologou a garantia. "
            "rejected = juiz indeferiu/recusou/rejeitou a garantia. "
            "replaced = garantia substituída (logged, exige successor lookup). "
            "closed = encerrada (ver closed_reason)."
        ),
    )
    confidence: float = Field(
        default=0.5,
        description=(
            "Confiança na classificação (0.0-1.0). "
            "Alta (>=0.8) quando há keyword textual explícita + contexto coerente. "
            "Média (~0.6) quando inferido sem keyword direta. "
            "Baixa (<0.5) quando texto é ambíguo."
        ),
    )
    reasoning: Optional[str] = Field(
        default=None,
        description=(
            "Justificativa curta (até 300 chars). Cite a keyword detectada + "
            "trecho do movement_text. Útil pra audit."
        ),
    )
    closed_reason: Optional[
        Literal[
            "extinto_processo",
            "sinistro_pago",
            "liberada",
            "outra",
        ]
    ] = Field(
        default=None,
        description=(
            "OBRIGATÓRIO quando new_state='closed', NULL pros outros estados. "
            "extinto_processo = processo principal extinto sem julgamento. "
            "sinistro_pago = pagamento de indenização securitária. "
            "liberada = liberação da garantia/baixa, sem sinistro. "
            "outra = qualquer outro motivo de encerramento."
        ),
    )


# ── Request / Response wrappers ──────────────────────────────────────────


class CourtStateClassifierRequest(BaseModel):
    """Input pro classifier: movement_text + current_state + presentation_kind."""

    movement_text: str = Field(
        description=(
            "Texto livre do movimento (processos_movimentos.descricao). "
            "Costuma carregar a keyword explícita ('acolho a garantia', "
            "'indefiro a apólice', 'declaro extinto', etc.). "
            "Prompt builder trunca em 4000 chars."
        ),
    )
    current_state: Literal[
        "offered",
        "presumed_accepted",
        "accepted",
        "rejected",
        "replaced",
        "closed",
    ] = Field(
        description=(
            "Estado atual da court_presentation. Só 'offered' ou "
            "'presumed_accepted' são elegíveis pra promoção (terminais "
            "retornam current_state com confidence=1.0)."
        ),
    )
    presentation_kind: Literal[
        "judicial",
        "carf",
        "pgfn",
        "tit_sp",
        "aiim_tit_sp",
    ] = Field(
        default="judicial",
        description=(
            "Kind do court_presentation. V1: 'judicial' é o único calibrado. "
            "Outros reservados Fase 3 (worker hoje filtra case_kind='judicial' "
            "no SQL)."
        ),
    )
    data_movimento: Optional[str] = Field(
        default=None,
        description="ISO date do movimento (contexto, NÃO é classificado).",
    )
    processo_numero: Optional[str] = Field(
        default=None,
        description="CNJ formatado (contexto, NÃO é classificado).",
    )
    model: Optional[str] = Field(
        default=None,
        description="Override do modelo (default: gemini-2.5-flash-lite via env).",
    )
    provider: Optional[str] = Field(
        default=None,
        description="Override do provider (default: gemini).",
    )


class CourtStateClassifierResponse(BaseModel):
    """Wrapped output do endpoint."""

    classification: CourtStateClassification
    raw_response: Optional[str] = None
    prompt_version: Optional[str] = None
    usage: Optional[dict[str, Any]] = None

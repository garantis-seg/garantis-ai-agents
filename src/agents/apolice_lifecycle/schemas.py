"""Pydantic schemas for apolice_lifecycle agent."""

from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


# ── Output schema ────────────────────────────────────────────────────────


class LifecycleEvidence(BaseModel):
    """Evidence pointer for a lifecycle event (apresentacao or acceptance)."""

    mov_id: Optional[str] = Field(
        default=None,
        description="ID estável da movimentação onde o evento foi detectado (ex: 'esc_12345', 'mov_id da fonte').",
    )
    mov_data: Optional[str] = Field(
        default=None,
        description="Data da movimentação no formato YYYY-MM-DD.",
    )
    snippet: Optional[str] = Field(
        default=None,
        description="Trecho exato (até 300 chars) da movimentação que justifica a classificação. "
        "Útil pra audit / explicabilidade.",
    )


class ApoliceLifecycleResult(BaseModel):
    """Lifecycle de uma apólice no contexto de um processo específico.

    Output do LLM. Frontend-api persiste em leads.apolice_processos colunas
    presented_at, presented_evidence, acceptance_status, etc.
    """

    apresentada: Optional[bool] = Field(
        default=None,
        description="True se a apólice foi efetivamente apresentada nos autos como garantia. "
        "False se há indicação explícita de NÃO apresentação ou recusa antes de protocolar. "
        "null se não há sinal nas movs (ainda não consta nos autos).",
    )
    presented_at: Optional[str] = Field(
        default=None,
        description="Data da apresentação (YYYY-MM-DD). Null se apresentada=False/null.",
    )
    presented_evidence: Optional[LifecycleEvidence] = Field(
        default=None,
        description="Evidência da apresentação. Null se apresentada=False/null.",
    )

    acceptance_status: Optional[Literal["pendente", "aceita", "recusada", "dispensada"]] = Field(
        default=None,
        description=(
            "Status da aceitação da apólice no processo. "
            "pendente=apresentada mas decisão judicial ainda não saiu. "
            "aceita=juiz acolheu como garantia idônea. "
            "recusada=juiz rejeitou (com motivo). "
            "dispensada=garantia substituída por outra forma (penhora, depósito, etc.). "
            "null se apresentada=null."
        ),
    )
    acceptance_decision_at: Optional[str] = Field(
        default=None,
        description="Data da decisão de aceitação/recusa (YYYY-MM-DD). Null se acceptance_status=pendente/null.",
    )
    acceptance_reason: Optional[str] = Field(
        default=None,
        description=(
            "Motivo livre quando acceptance_status='recusada' (ex: 'valor inferior à dívida', "
            "'apólice vencida', 'seguradora não admitida'). Null para outros status."
        ),
    )
    acceptance_evidence: Optional[LifecycleEvidence] = Field(
        default=None,
        description="Evidência da aceitação/recusa. Null se acceptance_status=pendente/null.",
    )

    confidence: float = Field(
        default=0.5,
        description="Confiança na extração (0.0-1.0). Baixa quando movs ambíguas, alta quando explícito.",
    )
    notes: Optional[str] = Field(
        default=None,
        description="Observações sobre qualidade dos dados ou ambiguidade.",
    )


# ── Request / Response wrappers ──────────────────────────────────────────


class ApoliceContext(BaseModel):
    """Apólice info passed as context to the LLM (não extrai estes campos, usa pra disambiguar)."""

    numero_apolice: str
    numero_apolice_formatado: Optional[str] = None
    seguradora: Optional[str] = None
    valor_is: Optional[float] = None
    data_inicio: Optional[str] = None
    data_termino: Optional[str] = None
    cnpj_tomador: Optional[str] = None
    nome_tomador: Optional[str] = None


class MovimentacaoInput(BaseModel):
    """Uma movimentação processual com data + texto + ID."""

    mov_id: Optional[str] = Field(
        default=None,
        description="ID estável da fonte (Escavador, Caderno PJe, Datajud, etc).",
    )
    data: Optional[str] = Field(default=None, description="YYYY-MM-DD")
    tipo: Optional[str] = Field(default=None, description="Classe/tipo da movimentação se disponível")
    texto: str = Field(description="Texto integral da movimentação ou andamento")


class ApoliceLifecycleRequest(BaseModel):
    """Input pro extrator: apólice + movs do processo."""

    apolice: ApoliceContext
    processo_numero: str = Field(description="CNJ do processo onde a apólice está sendo avaliada")
    movimentacoes: list[MovimentacaoInput] = Field(
        default_factory=list,
        description="Movs ordenadas cronologicamente (mais antigas primeiro). "
        "Recomenda-se enviar até 100 movs mais recentes — LLM tem context limit.",
    )
    model: Optional[str] = Field(
        default=None,
        description="Override do modelo (default: gemini-2.5-flash-lite via env).",
    )
    provider: Optional[str] = Field(
        default=None,
        description="Override do provider (default: gemini).",
    )


class ApoliceLifecycleResponse(BaseModel):
    """Wrapped output do endpoint."""

    lifecycle: ApoliceLifecycleResult
    raw_response: Optional[str] = None
    usage: Optional[dict[str, Any]] = None

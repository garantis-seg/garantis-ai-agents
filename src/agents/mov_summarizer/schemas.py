"""Pydantic schemas pro mov_summarizer agent.

Output deve ser compativel com kind='movimentacao' summary spec em
prompts/risk-engine-v5-card-schemas.md (Fase 0).
"""

from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


# ── Output card ──────────────────────────────────────────────────────────


class MovFlags(BaseModel):
    """Booleans rapidos pra indexar movs."""

    menciona_apolice: bool = False
    menciona_cda: bool = False
    menciona_aiim: bool = False
    menciona_acordo: bool = False
    menciona_recurso: bool = False
    menciona_transito: bool = False
    menciona_suspensao: bool = False
    menciona_recuperacao_judicial: bool = False
    menciona_processo_conexo: list[str] = Field(
        default_factory=list,
        description="Lista de CNJs (formatados ou raw) mencionados no texto da mov",
    )


class DecisaoDeMerito(BaseModel):
    """Quando a mov contem uma decisao de merito."""

    natureza: Literal[
        "procedente",
        "improcedente",
        "parcialmente_procedente",
        "extinto_sem_merito",
        "homologatoria",
    ] = Field(description="Natureza da decisao")
    instancia: Optional[Literal["1g", "2g", "stj", "stf"]] = None
    favoravel_tomador: Optional[bool] = Field(
        default=None,
        description="True se a decisao favoreceu o Tomador (executado em exec fiscal). null se ambiguo.",
    )
    transito_certificado: bool = False


class MovCardSummary(BaseModel):
    """Resumo estruturado de uma movimentacao. Cabe direto em
    dossier_artifacts.summary com kind='movimentacao'."""

    mov_id: str = Field(description="ID estavel da fonte (echo do input)")
    data: Optional[str] = Field(default=None, description="YYYY-MM-DD")
    tipo_origem: Optional[str] = Field(
        default=None,
        description="Tipo bruto da fonte (ex: 'PUBLICACAO', 'DECISAO_INTERLOCUTORIA') quando disponivel",
    )
    tipo_canonico: Literal[
        "sentenca",
        "acordao",
        "despacho",
        "decisao_interlocutoria",
        "peticao",
        "certidao",
        "intimacao",
        "publicacao",
        "ato_ordinatorio",
        "carga",
        "baixa",
        "conclusao",
        "outros",
    ] = Field(description="Classificacao canonica do tipo da mov")
    subtipo: Optional[str] = Field(default=None, description="Texto livre quando aplicavel")
    texto_resumo: str = Field(
        description="1-3 frases descrevendo o conteudo da mov + qualquer doc anexo. PT-BR."
    )
    flags: MovFlags = Field(default_factory=MovFlags)
    decisao_de_merito: Optional[DecisaoDeMerito] = None


# ── Request / Response ───────────────────────────────────────────────────


class MovInput(BaseModel):
    mov_id: str
    data: Optional[str] = None
    tipo: Optional[str] = None  # tipo bruto da fonte
    texto: str


class ProcessoContext(BaseModel):
    """Contexto minimo do processo pra desambiguar mov isolada."""

    cnj: str
    classe: Optional[str] = None
    classe_cnj_code: Optional[int] = None
    polo_ativo: Optional[str] = None
    polo_passivo: Optional[str] = None


class MovSummarizerRequest(BaseModel):
    processo: ProcessoContext
    mov: MovInput
    model: Optional[str] = None
    provider: Optional[str] = None


class MovSummarizerResponse(BaseModel):
    card: MovCardSummary
    raw_response: Optional[str] = None
    usage: Optional[dict[str, Any]] = None

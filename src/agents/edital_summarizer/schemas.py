"""
Schemas for Edital Summarizer Agent.

Defines Pydantic models for edital summarization requests and responses.
These models serve dual purpose:
1. API request/response validation (FastAPI)
2. Structured output schema for Gemini (response_schema parameter)
"""

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


# --- Input schemas ---


class EditalItem(BaseModel):
    """A procurement item from the edital."""

    descricao: str = Field(description="Item description")
    quantidade: Optional[str] = Field(default=None, description="Quantity + unit")
    valor_unitario: Optional[str] = Field(default=None, description="Unit value")
    valor_total: Optional[str] = Field(default=None, description="Total value")


class EditalMetadata(BaseModel):
    """Structured metadata from the database (not from document text)."""

    numero: Optional[str] = Field(default=None, description="Edital number")
    orgao_nome: Optional[str] = Field(default=None, description="Government body name")
    modalidade: Optional[str] = Field(default=None, description="Bidding modality")
    valor_estimado: Optional[str] = Field(default=None, description="Estimated value (formatted)")
    data_encerramento: Optional[str] = Field(default=None, description="Closing date")
    modo_disputa: Optional[str] = Field(default=None, description="Dispute mode")
    itens: List[EditalItem] = Field(default=[], description="Top items by value")


class SummarizationRequest(BaseModel):
    """Request to generate an edital summary."""

    edital_metadata: EditalMetadata = Field(description="Structured metadata from DB")
    markdown_content: str = Field(description="Concatenated markdown from edital documents")
    provider: Optional[str] = Field(default=None, description="LLM provider")
    model: Optional[str] = Field(default=None, description="Model override")


# --- LLM Output schemas (used as Gemini response_schema) ---


class Identificacao(BaseModel):
    """Identification section of the edital."""

    numero: Optional[str] = Field(default=None, description="Edital number")
    objeto_detalhado: Optional[str] = Field(
        default=None, description="Detailed object description (2-4 sentences)"
    )
    modalidade: Optional[str] = Field(default=None, description="Bidding modality")
    amparo_legal: Optional[str] = Field(default=None, description="Legal basis")


class SessaoPublica(BaseModel):
    """Public session information."""

    data: Optional[str] = Field(default=None, description="Date (DD/MM/YYYY)")
    horario: Optional[str] = Field(default=None, description="Time (HH:MM)")
    modo_disputa: Optional[str] = Field(default=None, description="Dispute mode")
    criterio_julgamento: Optional[str] = Field(default=None, description="Judgment criteria")


class OrgaoResponsavel(BaseModel):
    """Responsible government body."""

    nome: Optional[str] = Field(default=None, description="Full name")
    email: Optional[str] = Field(default=None, description="Contact email")
    telefone: Optional[str] = Field(default=None, description="Contact phone")
    endereco: Optional[str] = Field(default=None, description="Address")


class GarantiaInfo(BaseModel):
    """Guarantee requirement details."""

    exigida: Optional[bool] = Field(default=None, description="Whether required")
    percentual: Optional[str] = Field(default=None, description="Percentage (e.g. '5%')")
    valor: Optional[str] = Field(default=None, description="Absolute value")
    modalidades_aceitas: Optional[str] = Field(
        default=None, description="Accepted modalities (seguro garantia, fianca bancaria, etc.)"
    )


class Detalhes(BaseModel):
    """Detailed bidding information."""

    valor_estimado: Optional[str] = Field(default=None, description="Estimated value or 'Sigiloso'")
    garantia_proposta: Optional[GarantiaInfo] = Field(default=None, description="Bid guarantee")
    garantia_contratual: Optional[GarantiaInfo] = Field(
        default=None, description="Contract/performance guarantee"
    )
    prazo_entrega: Optional[str] = Field(default=None, description="Delivery term")
    prazo_vigencia: Optional[str] = Field(default=None, description="Contract duration")
    margem_preferencia: Optional[bool] = Field(default=None, description="Has preference margin")
    preferencia_me_epp: Optional[bool] = Field(default=None, description="ME/EPP preference")
    exige_visita_tecnica: Optional[bool] = Field(default=None, description="Requires technical visit")
    exige_amostra: Optional[bool] = Field(default=None, description="Requires sample")
    permite_consorcio: Optional[bool] = Field(default=None, description="Allows consortium")
    subcontratacao: Optional[str] = Field(default=None, description="Subcontracting rules")


class ItemDestaque(BaseModel):
    """A highlighted procurement item."""

    descricao: str = Field(description="Item description")
    quantidade: Optional[str] = Field(default=None, description="Quantity")
    valor: Optional[str] = Field(default=None, description="Value")


class ItensResumo(BaseModel):
    """Summary of procurement items."""

    total_itens: Optional[int] = Field(default=None, description="Total number of items")
    categorias_principais: List[str] = Field(
        default=[], description="Main categories of items"
    )
    descricao_geral: Optional[str] = Field(
        default=None, description="General description of items (1-2 sentences)"
    )
    observacoes: Optional[str] = Field(default=None, description="Notable observations about items")
    itens_destaque: List[ItemDestaque] = Field(
        default=[], description="Top highlighted items"
    )


class Habilitacao(BaseModel):
    """Required qualification documents."""

    documentos_exigidos: List[str] = Field(
        default=[], description="Required documents for qualification"
    )
    qualificacao_tecnica: List[str] = Field(
        default=[], description="Technical qualification requirements"
    )
    qualificacao_economica: List[str] = Field(
        default=[], description="Financial qualification requirements"
    )


class OutrasInformacoes(BaseModel):
    """Other relevant information."""

    sistema_eletronico: Optional[str] = Field(
        default=None, description="Electronic bidding system"
    )
    validade_proposta: Optional[str] = Field(
        default=None, description="Proposal validity period"
    )
    certificacoes_exigidas: List[str] = Field(
        default=[], description="Required certifications"
    )
    condicoes_pagamento: Optional[str] = Field(
        default=None, description="Payment conditions summary"
    )
    indice_reajuste: Optional[str] = Field(default=None, description="Price adjustment index")
    penalidades_resumo: Optional[str] = Field(
        default=None, description="Summary of penalties"
    )


class Severidade(str, Enum):
    """Risk severity level."""

    ALTA = "alta"
    MEDIA = "media"
    BAIXA = "baixa"


class Risco(BaseModel):
    """An identified risk."""

    descricao: str = Field(description="Risk description")
    severidade: Severidade = Field(description="Severity: alta, media, baixa")


class Oportunidade(BaseModel):
    """An identified opportunity."""

    descricao: str = Field(description="Opportunity description")
    tipo: Optional[str] = Field(default=None, description="Type (garantia, ME/EPP, valor, etc.)")


class EditalSummaryLLMResponse(BaseModel):
    """
    Complete structured summary output from the LLM.

    This model is used as `response_schema` for Gemini structured output,
    ensuring the LLM returns valid JSON matching this schema.
    """

    identificacao: Identificacao = Field(default_factory=Identificacao)
    sessao_publica: SessaoPublica = Field(default_factory=SessaoPublica)
    orgao_responsavel: OrgaoResponsavel = Field(default_factory=OrgaoResponsavel)
    detalhes: Detalhes = Field(default_factory=Detalhes)
    itens: ItensResumo = Field(default_factory=ItensResumo)
    habilitacao: Habilitacao = Field(default_factory=Habilitacao)
    outras_informacoes: OutrasInformacoes = Field(default_factory=OutrasInformacoes)
    riscos: List[Risco] = Field(default=[], description="Identified risks")
    oportunidades: List[Oportunidade] = Field(default=[], description="Identified opportunities")
    resumo_executivo: str = Field(
        default="", description="Executive summary (3-5 sentences, professional tone)"
    )


# --- Map-Reduce schemas ---


class ChunkSummary(BaseModel):
    """Simplified summary extracted from a single document chunk (MAP pass)."""

    objeto: Optional[str] = Field(default=None, description="Object description found in chunk")
    garantia_proposta: Optional[str] = Field(default=None, description="Bid guarantee info found")
    garantia_contratual: Optional[str] = Field(default=None, description="Contract guarantee info found")
    valor_estimado: Optional[str] = Field(default=None, description="Estimated value found")
    prazo_entrega: Optional[str] = Field(default=None, description="Delivery term found")
    prazo_vigencia: Optional[str] = Field(default=None, description="Contract duration found")
    sessao_publica: Optional[str] = Field(default=None, description="Public session info found")
    orgao_contato: Optional[str] = Field(default=None, description="Contact info found")
    habilitacao: List[str] = Field(default=[], description="Qualification requirements found")
    penalidades: Optional[str] = Field(default=None, description="Penalties found")
    condicoes_pagamento: Optional[str] = Field(default=None, description="Payment conditions found")
    riscos_identificados: List[str] = Field(default=[], description="Risks identified")
    oportunidades_identificadas: List[str] = Field(default=[], description="Opportunities identified")
    informacoes_relevantes: List[str] = Field(default=[], description="Other relevant information")


# --- API response schemas ---


class SummarizationResponse(BaseModel):
    """API response from the summarization endpoint."""

    summary: EditalSummaryLLMResponse = Field(description="The structured summary")
    model: str = Field(description="Model used")
    provider: str = Field(description="Provider used")
    input_tokens: int = Field(default=0, description="Input tokens consumed")
    output_tokens: int = Field(default=0, description="Output tokens consumed")
    cost_usd: float = Field(default=0.0, description="Estimated cost in USD")
    success: bool = Field(default=True)
    error: Optional[str] = Field(default=None)
    strategy: str = Field(default="direct", description="Strategy used: direct or map_reduce")
    chunks_processed: int = Field(default=0, description="Number of chunks processed (map-reduce)")

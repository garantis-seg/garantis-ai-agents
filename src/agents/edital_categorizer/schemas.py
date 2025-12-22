"""
Schemas for Edital Categorizer Agent.

Defines Pydantic models for edital categorization requests and responses.
"""

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class BaseType(str, Enum):
    """L1 base type - Serviço or Produto."""
    SERVICO = "serviço"
    PRODUTO = "produto"


class EditalData(BaseModel):
    """Input data for an edital to be categorized."""

    id: Optional[str] = Field(default=None, description="Edital ID")
    title: str = Field(description="Título do edital")
    description: str = Field(default="", description="Descrição do edital")
    orgao_nome: Optional[str] = Field(default=None, description="Nome do órgão licitante")
    objeto_compra: Optional[str] = Field(default=None, description="Objeto da compra")
    modalidade_licitacao_nome: Optional[str] = Field(default=None, description="Modalidade da licitação")
    top_items: List[str] = Field(default=[], description="Principais itens por valor")

    def to_context_string(self) -> str:
        """Build context string for LLM analysis."""
        parts = []

        if self.title:
            parts.append(f"Título: {self.title}")
        if self.description:
            parts.append(f"Descrição: {self.description}")
        if self.orgao_nome:
            parts.append(f"Órgão: {self.orgao_nome}")
        if self.objeto_compra:
            parts.append(f"Objeto da Compra: {self.objeto_compra}")
        if self.top_items:
            items_text = "; ".join(self.top_items[:4])
            parts.append(f"Principais Itens: {items_text}")
        if self.modalidade_licitacao_nome:
            parts.append(f"Modalidade: {self.modalidade_licitacao_nome}")

        return " | ".join(parts)


class L1Result(BaseModel):
    """Result of L1 (base type) categorization."""

    id: int = Field(description="L1 category ID (1=Serviço, 2=Produto)")
    name: str = Field(description="Category name (serviço or produto)")
    confidence: float = Field(ge=0, le=1, description="Confidence score 0-1")
    success: bool = Field(default=True)
    error: Optional[str] = Field(default=None)


class L2Result(BaseModel):
    """Result of L2 categorization."""

    id: Optional[int] = Field(default=None, description="L2 category ID (null if new)")
    name: str = Field(description="L2 category name")
    confidence: float = Field(ge=0, le=1, description="Confidence score 0-1")
    is_new: bool = Field(default=False, description="Whether this is a new category")
    needs_review: bool = Field(default=False, description="Whether human review is needed")
    success: bool = Field(default=True)
    error: Optional[str] = Field(default=None)


class L3Result(BaseModel):
    """Result of L3 categorization."""

    id: Optional[int] = Field(default=None, description="L3 category ID (null if new)")
    name: str = Field(description="L3 category name")
    confidence: float = Field(ge=0, le=1, description="Confidence score 0-1")
    is_new: bool = Field(default=False, description="Whether this is a new category")
    needs_review: bool = Field(default=False, description="Whether human review is needed")
    success: bool = Field(default=True)
    error: Optional[str] = Field(default=None)


class ValidationResult(BaseModel):
    """Result of L2/L3 validation."""

    approved: bool = Field(description="Whether the categorization is approved")
    suggested_l2: Optional[str] = Field(default=None, description="Suggested L2 if not approved")
    suggested_l3: Optional[str] = Field(default=None, description="Suggested L3 if not approved")


class TitleOptimizationResult(BaseModel):
    """Result of title optimization."""

    optimized_title: str = Field(description="Optimized title (max 60 chars)")
    original_title: str = Field(description="Original title")
    success: bool = Field(default=True)
    error: Optional[str] = Field(default=None)


class CategorizationResult(BaseModel):
    """Complete categorization result for an edital."""

    edital_id: Optional[str] = Field(default=None)
    l1: L1Result = Field(description="L1 (base type) result")
    l2: L2Result = Field(description="L2 category result")
    l3: L3Result = Field(description="L3 subcategory result")
    validation: Optional[ValidationResult] = Field(default=None, description="Validation result")
    optimized_title: Optional[str] = Field(default=None, description="Optimized title")

    # Metadata
    provider: str = Field(default="gemini")
    model: str = Field(default="gemini-2.0-flash")
    tokens_used: int = Field(default=0)
    cost_usd: float = Field(default=0.0)


# Response schemas for structured LLM output

class L1LLMResponse(BaseModel):
    """Expected LLM response for L1 categorization."""
    id: int
    name: str
    confidence: float


class L2LLMResponse(BaseModel):
    """Expected LLM response for L2 categorization."""
    id: Optional[int] = None
    name: str
    confidence: float
    is_new: bool = False


class L3LLMResponse(BaseModel):
    """Expected LLM response for L3 categorization."""
    id: Optional[int] = None
    name: str
    confidence: float
    is_new: bool = False


class ValidationLLMResponse(BaseModel):
    """Expected LLM response for validation."""
    approved: bool
    suggested_l2: Optional[str] = None
    suggested_l3: Optional[str] = None


class TitleLLMResponse(BaseModel):
    """Expected LLM response for title optimization."""
    optimized_title: str

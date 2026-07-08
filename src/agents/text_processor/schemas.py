"""
Schemas for Text Processor Agent.
"""

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class KeyInfoExtractionRequest(BaseModel):
    """Request for key information extraction."""

    text: str = Field(description="Text to extract information from")
    fields: List[str] = Field(
        description="Fields to extract (e.g., ['cnpj', 'razao_social', 'endereco'])"
    )
    context: Optional[str] = Field(
        default=None, description="Additional context about the document type"
    )


class KeyInfoExtractionResult(BaseModel):
    """Result of key information extraction."""

    extracted_fields: Dict[str, Optional[str]] = Field(
        description="Dictionary of field names to extracted values"
    )
    confidence: Dict[str, float] = Field(
        description="Confidence scores for each extracted field"
    )
    success: bool = Field(default=True)
    error: Optional[str] = Field(default=None)


class LLMExtractionResponse(BaseModel):
    """Schema for LLM structured output for extraction."""

    extracted_fields: Dict[str, Optional[str]] = Field(
        description="Dictionary of field names to extracted values"
    )
    confidence: Dict[str, float] = Field(
        description="Confidence scores (0-1) for each field"
    )

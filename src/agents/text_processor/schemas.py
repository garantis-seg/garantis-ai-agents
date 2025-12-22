"""
Schemas for Text Processor Agent.
"""

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class OCRCorrectionRequest(BaseModel):
    """Request for OCR text correction."""

    text: str = Field(description="Text to correct")
    preserve_structure: bool = Field(
        default=True, description="Preserve markdown/formatting structure"
    )
    language: str = Field(default="pt-BR", description="Text language")


class OCRCorrectionResult(BaseModel):
    """Result of OCR correction."""

    original_length: int = Field(description="Original text length")
    corrected_length: int = Field(description="Corrected text length")
    corrected_text: str = Field(description="Corrected text")
    changes_made: bool = Field(description="Whether any changes were made")
    success: bool = Field(default=True)
    error: Optional[str] = Field(default=None)


class TextFormattingRequest(BaseModel):
    """Request for text formatting."""

    text: str = Field(description="Text to format")
    target_format: str = Field(
        default="markdown",
        description="Target format: 'markdown', 'plain', 'structured'"
    )
    preserve_line_breaks: bool = Field(default=True)


class TextFormattingResult(BaseModel):
    """Result of text formatting."""

    formatted_text: str = Field(description="Formatted text")
    format_applied: str = Field(description="Format that was applied")
    success: bool = Field(default=True)
    error: Optional[str] = Field(default=None)


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

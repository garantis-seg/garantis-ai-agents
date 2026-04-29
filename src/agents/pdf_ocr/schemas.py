"""
PDF OCR Agent schemas.
"""

from typing import Optional

from pydantic import BaseModel, Field


class PdfOcrRequest(BaseModel):
    """Request for PDF OCR conversion."""

    pdf_base64: str = Field(description="Base64-encoded PDF bytes")
    filename: str = Field(default="document.pdf", description="Original filename (for logging)")
    model: Optional[str] = Field(default=None, description="Gemini model (default: gemini-2.5-flash-lite)")
    provider: Optional[str] = Field(default=None, description="LLM provider (default: gemini)")


class PdfOcrResult(BaseModel):
    """Result of PDF OCR conversion."""

    markdown_text: str = ""
    page_count: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    cost_usd: float = 0.0
    model_used: str = ""
    chunks_processed: int = 0
    success: bool = True
    error: Optional[str] = None

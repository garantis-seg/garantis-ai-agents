"""
PDF OCR Agent - Convert scanned PDFs to Markdown using Gemini Vision.
"""

from .agent import convert_pdf_to_markdown
from .schemas import PdfOcrRequest, PdfOcrResult

__all__ = [
    "convert_pdf_to_markdown",
    "PdfOcrRequest",
    "PdfOcrResult",
]

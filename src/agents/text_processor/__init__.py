"""
Text Processor Agent - AI-powered text processing and correction.

Provides OCR correction, text formatting, and other text processing tasks.
"""

from .agent import (
    TextProcessorAgent,
    correct_ocr_text,
    format_text,
    extract_key_info,
)
from .schemas import (
    OCRCorrectionRequest,
    OCRCorrectionResult,
    TextFormattingRequest,
    TextFormattingResult,
    KeyInfoExtractionRequest,
    KeyInfoExtractionResult,
)

__all__ = [
    "TextProcessorAgent",
    "correct_ocr_text",
    "format_text",
    "extract_key_info",
    "OCRCorrectionRequest",
    "OCRCorrectionResult",
    "TextFormattingRequest",
    "TextFormattingResult",
    "KeyInfoExtractionRequest",
    "KeyInfoExtractionResult",
]

"""
Text Processor Agent - AI-powered text processing and correction.

Provides key information extraction and other text processing tasks.
"""

from .agent import (
    extract_key_info,
)
from .schemas import (
    KeyInfoExtractionRequest,
    KeyInfoExtractionResult,
)

__all__ = [
    "extract_key_info",
    "KeyInfoExtractionRequest",
    "KeyInfoExtractionResult",
]

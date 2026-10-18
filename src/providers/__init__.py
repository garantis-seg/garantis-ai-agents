"""
O provider LLM da casa: só o Gemini (`create_provider`, em factory.py).
"""

from .base import BaseLLMProvider, LLMResponse
from .factory import create_provider

__all__ = [
    "BaseLLMProvider",
    "LLMResponse",
    "create_provider",
]

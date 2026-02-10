"""
Edital Summarizer Agent.

Generates comprehensive structured summaries of government bidding documents (editais).
"""

from .agent import EditalSummarizerAgent, generate_summary
from .schemas import (
    EditalMetadata,
    EditalSummaryLLMResponse,
    SummarizationRequest,
    SummarizationResponse,
)

__all__ = [
    "EditalSummarizerAgent",
    "generate_summary",
    "EditalMetadata",
    "EditalSummaryLLMResponse",
    "SummarizationRequest",
    "SummarizationResponse",
]

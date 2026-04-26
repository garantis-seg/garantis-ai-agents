"""
Edital Summarizer Agent.

Generates comprehensive structured summaries of government bidding documents (editais).
"""

from .agent import generate_summary
from .schemas import (
    ChunkSummary,
    EditalMetadata,
    EditalSummaryLLMResponse,
    SummarizationRequest,
    SummarizationResponse,
)

__all__ = [
    "generate_summary",
    "ChunkSummary",
    "EditalMetadata",
    "EditalSummaryLLMResponse",
    "SummarizationRequest",
    "SummarizationResponse",
]

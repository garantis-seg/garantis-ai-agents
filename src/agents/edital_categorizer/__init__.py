"""
Edital Categorizer Agent.

Categorizes government bidding documents (editais) into L1/L2/L3 hierarchy.
"""

from .agent import (
    EditalCategorizerAgent,
    categorize_edital,
    categorize_l1,
    categorize_l2,
    categorize_l3,
    optimize_title,
)
from .schemas import (
    EditalData,
    L1Result,
    L2Result,
    L3Result,
    CategorizationResult,
    TitleOptimizationResult,
)

__all__ = [
    "EditalCategorizerAgent",
    "categorize_edital",
    "categorize_l1",
    "categorize_l2",
    "categorize_l3",
    "optimize_title",
    "EditalData",
    "L1Result",
    "L2Result",
    "L3Result",
    "CategorizationResult",
    "TitleOptimizationResult",
]

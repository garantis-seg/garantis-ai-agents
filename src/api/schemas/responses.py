"""
Response schemas para a API.
"""

from typing import Any, Dict, List
from pydantic import BaseModel


class PromptsResponse(BaseModel):
    """Response da listagem de prompts."""
    agent: str
    active_version: str
    versions: List[Dict[str, Any]]


class HealthResponse(BaseModel):
    """Response do health check."""
    status: str
    version: str
    model_default: str
    prompt_default: str

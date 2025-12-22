"""
Health check endpoint.
"""

import os
from fastapi import APIRouter

from ..schemas.responses import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """
    Health check do serviço.

    Verifica se o serviço está rodando e retorna configurações padrão.
    """
    return HealthResponse(
        status="healthy",
        version="0.1.0",
        model_default=os.getenv("DEFAULT_MODEL", "gemini-2.0-flash"),
        prompt_default=os.getenv("DEFAULT_PROMPT_VERSION", "v3"),
    )

"""
Endpoints para gerenciamento de prompts.
"""

from fastapi import APIRouter, HTTPException

from ...prompts.loader import PromptLoader
from ..schemas.responses import PromptsResponse

router = APIRouter(prefix="/prompts", tags=["prompts"])


@router.get("/timing", response_model=PromptsResponse)
async def list_timing_prompts():
    """
    Lista versões de prompts disponíveis para timing analysis.
    """
    loader = PromptLoader()

    try:
        active = loader.get_active_version("timing_analysis")
        versions = loader.list_versions("timing_analysis")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return PromptsResponse(
        agent="timing_analysis",
        active_version=active or "v3",
        versions=versions,
    )


@router.get("/", response_model=list)
async def list_agents():
    """
    Lista todos os agentes disponíveis.
    """
    loader = PromptLoader()
    return loader.list_agents()

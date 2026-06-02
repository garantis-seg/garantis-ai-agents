"""
Endpoints para gerenciamento de prompts.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse

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


@router.get("/timing/content", response_class=PlainTextResponse)
async def get_timing_prompt_content(
    version: Optional[str] = Query(None, description="Versão do prompt (ex: v3). Se omitido, retorna a versão ativa.")
):
    """
    Retorna o conteúdo raw do prompt de timing analysis.

    Útil para sincronização com outros sistemas (ex: poc-prompt-benchmark).
    """
    loader = PromptLoader()

    try:
        content = loader.get_raw_prompt("timing_analysis", version)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return content


@router.get("/", response_model=list)
async def list_agents():
    """
    Lista todos os agentes disponíveis.
    """
    loader = PromptLoader()
    return loader.list_agents()


@router.get("/engine-v6/raw-templates")
async def engine_v6_raw_templates():
    """Templates CRUS dos prompts engine v6 (L1 mov/day + L2 + L3).

    Retorna `{layer: template}` onde `layer` espelha leads.engine_llm_calls
    (layer1_mov_factsheet, layer1_day_factsheet,
    layer2_processo_synthesis, layer3_merito_synthesis).

    Cada template eh o ESQUELETO do prompt — instrucoes/regras estaticas — sem
    dados do caso, com `{{campo}}` nas injecoes. Gerado reaproveitando os
    proprios builders de prompt (zero-drift). Consumido pela aba "Prompt Raw"
    do debug-llm no garantis-app (via proxy frontend-api /api/risk-v6/prompt-
    templates). Estatico — pode ser cacheado agressivamente pelo caller.
    """
    from ...agents._raw_templates import get_raw_prompt_templates

    return get_raw_prompt_templates()

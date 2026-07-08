"""
Endpoints para gerenciamento de prompts.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/prompts", tags=["prompts"])


@router.get("/engine-v6/raw-templates")
async def engine_v6_raw_templates():
    """Templates CRUS dos prompts engine v6 (L1 mov + L2 + L3).

    Retorna `{layer: template}` onde `layer` espelha leads.engine_llm_calls
    (layer1_mov_factsheet, layer2_processo_synthesis,
    layer3_merito_synthesis). layer1_day_factsheet saiu em 2026-06-13
    (teardown do tier por-dia).

    Cada template eh o ESQUELETO do prompt — instrucoes/regras estaticas — sem
    dados do caso, com `{{campo}}` nas injecoes. Gerado reaproveitando os
    proprios builders de prompt (zero-drift). Consumido pela aba "Prompt Raw"
    do debug-llm no garantis-app (via proxy frontend-api /api/risk-v6/prompt-
    templates). Estatico — pode ser cacheado agressivamente pelo caller.
    """
    from ...agents._raw_templates import get_raw_prompt_templates

    return get_raw_prompt_templates()

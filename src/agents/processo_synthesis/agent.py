"""Processo Synthesis Agent - engine v6_meritos camada 2.

Single LLM call por PROCESSO, sintetiza N mov_factsheets + apolice context
em 7 campos estruturados (estado processual, decisao vigente, lifecycle garantia,
risco intermediario, trajetoria, peca-pivo candidata, valores).

Output cabe em leads.dossier_artifacts com kind='processo_synthesis'.
"""

import json
import logging
import os
from typing import Optional

from ...providers import create_provider
from ...providers.base import LLMResponse
from ...utils.llm_json import parse_llm_json
from .prompts import build_processo_synthesis_prompt
from .schemas import ProcessoSynthesisCard, ProcessoSynthesisRequest

logger = logging.getLogger(__name__)

# Default model: gemini-2.5-flash (nao Lite) - sintese precisa de mais qualidade
# que mov_factsheet. Override via env.
DEFAULT_MODEL = os.getenv("PROCESSO_SYNTHESIS_MODEL", "gemini-2.5-flash")
DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER", "gemini")


async def classify_processo_synthesis(
    request: ProcessoSynthesisRequest | dict,
    model: Optional[str] = None,
    provider: str = DEFAULT_PROVIDER,
) -> dict:
    """Synthesize a processo from its mov_factsheets + apolice context.

    Returns:
        {"card": ProcessoSynthesisCard.model_dump() | error_dict,
         "raw_response": str, "usage": dict}
    """
    if isinstance(request, dict):
        request = ProcessoSynthesisRequest(**request)

    if model is None:
        model = DEFAULT_MODEL

    llm_provider = create_provider(provider)
    prompt = build_processo_synthesis_prompt(request)

    # NOTA: response_schema dropado (Gemini Developer API rejeita
    # additionalProperties gerado por dict[str, Any] no schema). parse_llm_json
    # extrai JSON do texto livre com fallback regex.
    response: LLMResponse = await llm_provider.agenerate(
        prompt=prompt,
        model=model,
        temperature=0.1,
    )

    raw_response = response.text
    try:
        parsed = parse_llm_json(raw_response)
        # Echo input identifiers
        parsed.setdefault("processo_numero", request.processo_numero)
        if request.classe and not parsed.get("classe"):
            parsed["classe"] = request.classe
        if request.classe_cnj_code is not None and parsed.get("classe_cnj_code") is None:
            parsed["classe_cnj_code"] = request.classe_cnj_code
        if request.role_no_merito and not parsed.get("role_no_merito"):
            parsed["role_no_merito"] = request.role_no_merito
        if not parsed.get("movs_processed"):
            parsed["movs_processed"] = len(request.mov_factsheets or [])
        card = ProcessoSynthesisCard(**parsed)
        card_data = card.model_dump()
    except (json.JSONDecodeError, Exception) as e:
        logger.error(f"processo_synthesis parse failed pn={request.processo_numero}: {repr(e)}")
        card_data = {
            "error": repr(e), "raw": raw_response,
            "processo_numero": request.processo_numero,
        }

    usage = {
        "input_tokens": response.input_tokens or 0,
        "output_tokens": response.output_tokens or 0,
        "total_tokens": (response.input_tokens or 0) + (response.output_tokens or 0),
        "cost_usd": (response.metadata.get("cost_usd", 0.0) if response.metadata else 0.0),
        "model": model,
        "provider": provider,
    }

    return {
        "card": card_data,
        "raw_response": raw_response,
        "usage": usage,
    }

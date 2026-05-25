"""Merito Synthesis Agent - engine v6_meritos camada 3 (OUTPUT PRIMARIO).

Single LLM call por MERITO. Recebe processo_syntheses de TODOS processos do
merito + tomador + cda/aiim + jurisprudencia + snapshot anterior. Output:
risco + justificativa + trajetoria + peca_pivo + proximos_passos.

Persiste em monitoramento.risk_snapshots (orchestrator no frontend-api).
"""

import json
import logging
import os
from typing import Optional

from ...providers import create_provider
from ...providers.base import LLMResponse
from ...utils.llm_json import parse_llm_json
from .prompts import build_prompt_and_version
from .schemas import MeritoSynthesisCard, MeritoSynthesisRequest

logger = logging.getLogger(__name__)

# Default Flash (sintese final precisa de qualidade). Pro pode ser override via env
# quando o usuario quiser maior performance ao custo de 8x preco.
DEFAULT_MODEL = os.getenv("MERITO_SYNTHESIS_MODEL", "gemini-2.5-flash")
DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER", "gemini")


async def classify_merito_synthesis(
    request: MeritoSynthesisRequest | dict,
    model: Optional[str] = None,
    provider: str = DEFAULT_PROVIDER,
) -> dict:
    """Synthesize a merito from its processo_syntheses + context cards.

    Returns:
        {"card": MeritoSynthesisCard.model_dump() | error_dict,
         "raw_response": str,
         "llm_raw_prompt": str,
         "usage": dict}
    """
    if isinstance(request, dict):
        request = MeritoSynthesisRequest(**request)

    if model is None:
        model = DEFAULT_MODEL

    llm_provider = create_provider(provider)
    prompt, prompt_version = build_prompt_and_version(request)

    # v2.1: response_schema=MeritoSynthesisCard reativado depois que schema
    # foi reformatado pra eliminar dict[str, Any] (causa do additionalProperties
    # bug que tinha levado o response_schema a ser dropado). BreakdownProcesso
    # + CardsIndexCount substituem os dict legacy. Optional[str] enum
    # apertados pra Literal[...] strict pra evitar loop infinito decoder Gemini
    # (lição L2 v2.1).
    # Determinismo Bug 4 handoff: temperature=0.0 + thinking_budget=0 em
    # gemini-2.5-*. Provider aplica top_p=1.0, top_k=1 quando temp=0.
    response: LLMResponse = await llm_provider.agenerate(
        prompt=prompt,
        model=model,
        temperature=0.0,
        response_schema=MeritoSynthesisCard,
        thinking_budget=0,
    )

    raw_response = response.text
    try:
        parsed = parse_llm_json(raw_response)
        # Echo IDs in case LLM dropped them
        parsed.setdefault("merito_id", request.merito_id)
        parsed.setdefault("merito_context", request.merito_context)
        # Default cards_index aggregation if LLM didn't fill
        if not parsed.get("cards_index"):
            parsed["cards_index"] = {
                "processo_synthesis": len(request.processo_syntheses or []),
                "cda": len(request.cdas or []),
                "aiim": len(request.aiims or []),
                "tomador": 1 if request.tomador else 0,
                "jurisprudencia": 1 if request.jurisprudencia else 0,
            }
        card = MeritoSynthesisCard(**parsed)
        card_data = card.model_dump()
    except (json.JSONDecodeError, Exception) as e:
        logger.error(f"merito_synthesis parse failed merito_id={request.merito_id}: {repr(e)}")
        card_data = {
            "error": repr(e), "raw": raw_response,
            "merito_id": request.merito_id, "merito_context": request.merito_context,
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
        "llm_raw_prompt": prompt,
        "prompt_version": prompt_version,
        "usage": usage,
    }

"""Monolith FactSheet Agent — engine v6_meritos camada 1, tier monolitico.

Single LLM call por processo. Recebe texto do PDF monolitico inteiro
(cap'd 60k chars) e sintetiza em 1 MonolithFactsheetCard estruturado.

Substitui o uso direto de autos_raw_excerpt no L2 — preserva arquitetura RAG
onde L2 consome SO cards L1, nunca raw. Spec: memory engine-v6-pipeline-quality-tiers.
"""
import json
import logging
import os
from typing import Optional

from ...providers import create_provider
from ...providers.base import LLMResponse
from ...utils.llm_json import parse_llm_json
from .._utils import MODEL_VARIANT_TEXT, call_l1_with_vision_fallback
from .prompts import build_monolith_factsheet_prompt
from .schemas import (
    MonolithFactsheetCard,
    MonolithFactsheetRequest,
    ProcessoContextMin,
)

logger = logging.getLogger(__name__)

# Usado pra drift detection em leads.engine_llm_calls.prompt_version.
PROMPT_VERSION = "monolith_factsheet.v1.0"

# Unificado pra flash-lite (2026-05-27) — apples-to-apples com mov_factsheet e
# day_factsheet. Permite benchmark Vision vs Text mantendo modelo constante.
# Override via env MONOLITH_FACTSHEET_MODEL preserva escape hatch.
DEFAULT_MODEL = os.getenv("MONOLITH_FACTSHEET_MODEL", "gemini-2.5-flash-lite")
DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER", "gemini")


async def classify_monolith_factsheet(
    processo: ProcessoContextMin | dict,
    autos_text: str,
    total_pages: Optional[int] = None,
    pages_used: Optional[int] = None,
    truncated: bool = False,
    model: Optional[str] = None,
    provider: str = DEFAULT_PROVIDER,
    gcs_url: Optional[str] = None,
) -> dict:
    """Extract a MonolithFactsheetCard sintetizando PDF monolitico.

    Args:
        processo: contexto minimo (CNJ, classe, polos)
        autos_text: texto extraido do PDF (PyMuPDF pre_extracted_text)
        total_pages: paginas totais do PDF (audit)
        pages_used: paginas efetivamente lidas (primeiras N + ultimas M)
        truncated: True se texto excedeu cap
        model: override gemini model
        provider: 'gemini' (default)

    Returns:
        {"card": MonolithFactsheetCard.model_dump() | error_dict,
         "raw_response": str,
         "llm_raw_prompt": str,
         "usage": dict,
         "prompt_version": str}
    """
    if isinstance(processo, dict):
        processo = ProcessoContextMin(**processo)

    if model is None:
        model = DEFAULT_MODEL

    req = MonolithFactsheetRequest(
        processo=processo,
        autos_text=autos_text,
        total_pages=total_pages,
        pages_used=pages_used,
        truncated=truncated,
    )

    llm_provider = create_provider(provider)
    prompt = build_monolith_factsheet_prompt(req)

    response: LLMResponse = await call_l1_with_vision_fallback(
        llm_provider,
        model=model,
        prompt=prompt,
        gcs_urls=[gcs_url] if gcs_url else [],
        response_schema=MonolithFactsheetCard,
        log_label=f"cnj={processo.cnj}",
    )

    raw_response = response.text
    try:
        parsed = parse_llm_json(raw_response)
        parsed.setdefault("processo_numero", processo.cnj)
        if pages_used is not None and "pages_used" not in parsed:
            parsed["pages_used"] = pages_used
        card = MonolithFactsheetCard(**parsed)
        card_data = card.model_dump()
    except (json.JSONDecodeError, Exception) as e:
        logger.error(f"monolith_factsheet parse failed cnj={processo.cnj}: {repr(e)}")
        card_data = {"error": repr(e), "raw": raw_response, "processo_numero": processo.cnj}

    usage = {
        "input_tokens": response.input_tokens or 0,
        "output_tokens": response.output_tokens or 0,
        "total_tokens": (response.input_tokens or 0) + (response.output_tokens or 0),
        "cost_usd": (response.metadata.get("cost_usd", 0.0) if response.metadata else 0.0),
        "model": model,
        "provider": provider,
        "model_variant": (
            response.metadata.get("model_variant", MODEL_VARIANT_TEXT)
            if response.metadata else MODEL_VARIANT_TEXT
        ),
    }

    return {
        "card": card_data,
        "raw_response": raw_response,
        "llm_raw_prompt": prompt,
        "usage": usage,
        "prompt_version": PROMPT_VERSION,
    }

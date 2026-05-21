"""Day FactSheet Agent — engine v6_meritos camada 1, tier Degradado-Dia.

Single LLM call por DIA quando o tier do proc eh Degradado-Dia (docs com
texto sem FK nativa). LLM correlaciona movs+docs do mesmo dia.

Espelha estrutura do mov_factsheet agent mas com granularidade diaria.
"""
import json
import logging
import os
from typing import Optional

from ...providers import create_provider
from ...providers.base import LLMResponse
from ...utils.llm_json import parse_llm_json
from .prompts import build_day_factsheet_prompt
from .schemas import (
    DayDocInput,
    DayFactsheetCard,
    DayMovInput,
    ProcessoContextMin,
)

logger = logging.getLogger(__name__)

# gemini-2.5-flash (nao lite) pq correlacao multi-mov*multi-doc precisa mais qualidade
DEFAULT_MODEL = os.getenv("DAY_FACTSHEET_MODEL", "gemini-2.5-flash")
DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER", "gemini")


async def classify_day_factsheet(
    processo: ProcessoContextMin | dict,
    date: str,
    movs_no_dia: list[DayMovInput | dict] | None = None,
    docs_no_dia: list[DayDocInput | dict] | None = None,
    model: Optional[str] = None,
    provider: str = DEFAULT_PROVIDER,
) -> dict:
    """Extract a DayFactsheetCard sintetizando 1 dia inteiro de 1 proc.

    Args:
        processo: contexto minimo (CNJ, classe, polos)
        date: YYYY-MM-DD anchor
        movs_no_dia: movs registradas no dia
        docs_no_dia: docs juntados no dia (com text_content)
        model: override gemini model
        provider: 'gemini' (default)

    Returns:
        {"card": DayFactsheetCard.model_dump() | error_dict,
         "raw_response": str,
         "llm_raw_prompt": str,
         "usage": dict}
    """
    if isinstance(processo, dict):
        processo = ProcessoContextMin(**processo)

    movs_typed: list[DayMovInput] = []
    for m in movs_no_dia or []:
        movs_typed.append(m if isinstance(m, DayMovInput) else DayMovInput(**m))

    docs_typed: list[DayDocInput] = []
    for d in docs_no_dia or []:
        docs_typed.append(d if isinstance(d, DayDocInput) else DayDocInput(**d))

    if model is None:
        model = DEFAULT_MODEL

    llm_provider = create_provider(provider)
    prompt = build_day_factsheet_prompt(
        processo, date,
        movs_no_dia=movs_typed,
        docs_no_dia=docs_typed,
    )

    response: LLMResponse = await llm_provider.agenerate(
        prompt=prompt,
        model=model,
        temperature=0.0,
        response_schema=DayFactsheetCard,
    )

    raw_response = response.text
    try:
        parsed = parse_llm_json(raw_response)
        # Echo input identifiers em caso de LLM reset
        parsed.setdefault("processo_numero", processo.cnj)
        parsed.setdefault("date", date)
        card = DayFactsheetCard(**parsed)
        card_data = card.model_dump()
    except (json.JSONDecodeError, Exception) as e:
        logger.error(
            f"day_factsheet parse failed proc={processo.cnj} date={date}: {repr(e)}"
        )
        card_data = {
            "error": repr(e),
            "raw": raw_response,
            "processo_numero": processo.cnj,
            "date": date,
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
        "usage": usage,
    }

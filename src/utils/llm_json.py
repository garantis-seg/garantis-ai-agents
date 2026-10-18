"""Tolerant LLM JSON parser shared across agents.

Handles common LLM output quirks:
- code-fenced markdown wrappers (```json ... ```)
- arrays returned where dict expected (returns first element)
- "Extra data" trailing past first valid JSON object
- "Unterminated string" — truncates to last complete key/value pair
- top-level scalars are rejected explicitly

Used by the agents in `src/agents/`.

Each repair that changes the text logs `FALLBACK_DISPAROU familia=llm_json_conserto`, with
the repair and the caller module. Clean JSON does not log. The count tells, per agent, if
the parse can become strict where the call has a `response_schema`.
"""

from __future__ import annotations

import json
import logging
import re
import sys

logger = logging.getLogger(__name__)


def parse_llm_json(raw: str) -> dict:
    """Tolerant parser. Raises ValueError when input cannot become a dict."""
    text = (raw or "").strip()
    if not text:
        raise ValueError("empty LLM response")
    consertos: list[str] = []
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
        consertos.append("cerca")

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        msg = str(e)
        pos = getattr(e, "pos", None)
        if "Extra data" in msg and pos is not None:
            parsed = json.loads(text[:pos])
            consertos.append("extra_data")
        elif "Unterminated string" in msg and pos is not None:
            last_comma = text.rfind(",", 0, pos)
            if last_comma > 0:
                parsed = json.loads(text[:last_comma] + "}")
                consertos.append("string_aberta")
            else:
                raise
        else:
            last_brace = text.rfind("}")
            if last_brace > 0:
                parsed = json.loads(text[: last_brace + 1])
                consertos.append("corte_na_chave")
            else:
                raise

    if isinstance(parsed, list):
        parsed = parsed[0] if parsed else {}
        consertos.append("lista")
    if not isinstance(parsed, dict):
        raise ValueError(f"Expected JSON object, got {type(parsed).__name__}")
    if consertos:
        # O modulo de quem chamou identifica o agente sem mudar os chamadores.
        logger.warning(
            "FALLBACK_DISPAROU familia=%s conserto=%s chamador=%s",
            "llm_json_conserto", "+".join(consertos), sys._getframe(1).f_globals.get("__name__"),
        )
    return parsed

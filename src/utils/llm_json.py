"""Tolerant LLM JSON parser shared across agents.

Handles common LLM output quirks:
- code-fenced markdown wrappers (```json ... ```)
- arrays returned where dict expected (returns first element)
- "Extra data" trailing past first valid JSON object
- "Unterminated string" — truncates to last complete key/value pair
- top-level scalars are rejected explicitly

Used by risk_classifier, apolice_lifecycle, mov_summarizer agents and
the in-process v5_cards_classifier in frontend-api.
"""

from __future__ import annotations

import json
import re


def parse_llm_json(raw: str) -> dict:
    """Tolerant parser. Raises ValueError when input cannot become a dict."""
    text = (raw or "").strip()
    if not text:
        raise ValueError("empty LLM response")
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        msg = str(e)
        pos = getattr(e, "pos", None)
        if "Extra data" in msg and pos is not None:
            parsed = json.loads(text[:pos])
        elif "Unterminated string" in msg and pos is not None:
            last_comma = text.rfind(",", 0, pos)
            if last_comma > 0:
                parsed = json.loads(text[:last_comma] + "}")
            else:
                raise
        else:
            last_brace = text.rfind("}")
            if last_brace > 0:
                parsed = json.loads(text[: last_brace + 1])
            else:
                raise

    if isinstance(parsed, list):
        parsed = parsed[0] if parsed else {}
    if not isinstance(parsed, dict):
        raise ValueError(f"Expected JSON object, got {type(parsed).__name__}")
    return parsed

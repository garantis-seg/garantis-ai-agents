"""PromptFoo custom provider — chama o agente L1 mov_factsheet real.

Cobre o pipeline inteiro: prompt rendering + Gemini call + Pydantic parse.
Mudança em prompts.py, schemas.py ou agent.py dispara mudança no output do eval.

Spec do provider PromptFoo Python:
  https://www.promptfoo.dev/docs/providers/python/

Contract:
  def call_api(prompt: str, options: dict, context: dict) -> dict
  → { "output": <json string ou dict>, "tokenUsage": {...}, "cost": float }
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

# Garantis-ai-agents root no sys.path pra importar src.*
_THIS = Path(__file__).resolve()
_REPO_ROOT = _THIS.parent.parent.parent.parent  # evals/promptfoo/providers/X.py → repo root
sys.path.insert(0, str(_REPO_ROOT))

from src.agents.mov_factsheet import classify_mov_factsheet  # noqa: E402


def call_api(prompt: str, options: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Sync entrypoint exigido pelo PromptFoo. Delega pra coroutine.

    Args:
        prompt: ignorado (provider chama o agente que constroi prompt internamente).
        options: config do provider (não usado).
        context: { vars: { processo, mov, documentos_anexados, fallback_context, expected } }

    Returns:
        { "output": <json string do card>, "tokenUsage": {...}, "cost": float, "cached": false }
    """
    return asyncio.run(_call_api_async(context))


def _empty_to_none(d: dict[str, Any] | None) -> dict[str, Any] | None:
    """Snapshot YAML usa strings vazias / 0 como sentinels (PromptFoo nao aceita
    `null` top-level em vars). Converte de volta pra None antes do agent."""
    if not d:
        return d
    out = {}
    for k, v in d.items():
        if v == "" or v == 0 and k.endswith("_code"):
            out[k] = None
        else:
            out[k] = v
    return out


async def _call_api_async(context: dict[str, Any]) -> dict[str, Any]:
    vars_in = context.get("vars", {})
    processo = _empty_to_none(vars_in.get("processo"))
    mov = vars_in.get("mov")  # texto deve ser string nao-vazia; demais campos opcionais
    docs = vars_in.get("documentos_anexados") or []
    fb_ctx = vars_in.get("fallback_context")

    if not processo or not mov:
        return {
            "output": json.dumps({"error": "missing processo or mov in vars"}),
            "cost": 0.0,
        }

    try:
        result = await classify_mov_factsheet(
            processo=processo,
            mov=mov,
            documentos_anexados=docs,
            fallback_context=fb_ctx,
            # Default espelha o AGENTE de prod (src/agents/mov_factsheet/agent.py,
            # 3.1-flash-lite desde 2026-06-26). Drift 2.5 aqui deixava o eval
            # testando modelo errado E morto no Vertex (400: max_tokens=65536 >
            # limite 65535 da familia 2.5) — F0 do projeto 2.5→3.1, 2026-07-21.
            model=os.getenv("MOV_FACTSHEET_MODEL", "gemini-3.1-flash-lite"),
            provider=os.getenv("DEFAULT_PROVIDER", "gemini"),
        )
    except Exception as e:
        return {
            "output": json.dumps({"error": repr(e)}),
            "cost": 0.0,
        }

    card = result.get("card", {})
    usage = result.get("usage", {}) or {}

    return {
        "output": json.dumps(card, ensure_ascii=False),
        "tokenUsage": {
            "prompt": usage.get("input_tokens", 0),
            "completion": usage.get("output_tokens", 0),
            "total": usage.get("total_tokens", 0),
        },
        "cost": float(usage.get("cost_usd") or 0.0),
        "cached": False,
    }

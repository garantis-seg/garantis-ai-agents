"""Regressao: fallback de cards_index nao pode referenciar campos removidos.

Bug latente achado na revisao L2/L3 2026-06-12: agent.py construia o fallback
de cards_index lendo `request.jurisprudencia` (campo REMOVIDO do schema na
v2.2). Pydantic v2 levanta AttributeError em campo inexistente; o except
amplo do parse engolia o erro, e um output LLM VALIDO virava parse-error
(card {"error": ...} persistido como snapshot de erro) sempre que o LLM
omitisse cards_index.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import src.agents.merito_synthesis.agent as agent_mod
from src.agents.merito_synthesis.schemas import (
    MeritoSynthesisRequest,
    ProcessoSynthesisMin,
)


class _FakeProvider:
    """Provider fake: devolve texto fixo sem chamar LLM."""

    def __init__(self, text: str):
        self._text = text

    async def agenerate(self, **kwargs):
        return SimpleNamespace(
            text=self._text,
            input_tokens=10,
            output_tokens=5,
            metadata={},
        )


def test_card_valido_sem_cards_index_nao_vira_parse_error(monkeypatch):
    """LLM omite cards_index -> fallback monta do request SEM AttributeError."""
    card_json = json.dumps(
        {
            "merito_id": 1,
            "merito_context": "global",
            "risco": "Baixo",
            "justificativa": "ok",
        }
    )
    monkeypatch.setattr(
        agent_mod, "create_provider", lambda p: _FakeProvider(card_json)
    )
    req = MeritoSynthesisRequest(
        merito_id=1,
        processo_syntheses=[
            ProcessoSynthesisMin(processo_numero="0000000-00.0000.0.00.0000")
        ],
    )

    out = asyncio.run(agent_mod.classify_merito_synthesis(req))

    assert "error" not in out["card"], out["card"]
    assert out["card"]["cards_index"]["processo_synthesis"] == 1
    # Campo segue no CardsIndexCount (response_schema) com default 0 —
    # so a LEITURA de request.jurisprudencia morreu.
    assert out["card"]["cards_index"]["jurisprudencia"] == 0

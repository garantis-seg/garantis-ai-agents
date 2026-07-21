"""Harness promptfoo — regressão do 'Event loop is closed' (F0 2.5→3.1, 2026-07-21).

O provider promptfoo tem entrypoint SYNC (`call_api`) chamado 1x por caso.
Antes: `asyncio.run()` por caso → loop novo criado E FECHADO a cada caso,
enquanto `LLMFactory._instances` cacheia o provider (client httpx do
google-genai preso ao loop do 1º caso) → a partir do 2º caso, ~50% estourava
RuntimeError('Event loop is closed').

Fix (eval-only, no provider do promptfoo): UM loop persistente do processo
(`_LOOP.run_until_complete` por caso). Este teste afirma a propriedade que
elimina o bug: 2 casos consecutivos rodam no MESMO loop, que segue ABERTO —
condição suficiente pra um client cacheado nunca ver o próprio loop fechado.
Com o `asyncio.run()` antigo, os 2 asserts finais falham (loops distintos,
1º fechado).
"""
import asyncio
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "evals" / "promptfoo" / "providers"))

import mov_factsheet_provider as provider_mod  # noqa: E402


def test_two_consecutive_cases_share_one_open_loop(monkeypatch):
    seen_loops = []

    async def fake_classify(**kwargs):
        seen_loops.append(asyncio.get_running_loop())
        return {"card": {"ok": True}, "usage": {}}

    monkeypatch.setattr(provider_mod, "classify_mov_factsheet", fake_classify)

    ctx = {"vars": {"processo": {"numero": "1"}, "mov": {"texto": "despacho"}}}
    out1 = provider_mod.call_api("", {}, ctx)
    out2 = provider_mod.call_api("", {}, ctx)

    assert "Event loop is closed" not in out1["output"]
    assert "Event loop is closed" not in out2["output"]
    assert len(seen_loops) == 2
    # A propriedade central: mesmo loop nos 2 casos, e ele continua aberto.
    assert seen_loops[0] is seen_loops[1]
    assert not seen_loops[0].is_closed()

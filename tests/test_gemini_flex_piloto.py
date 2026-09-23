"""Piloto Flex PayGo (2026-09-23): o middleware marca SO o L1 classify, e o provider
manda os headers do Flex nessa request e refaz no Standard em QUALQUER falha do Flex
(timeout, 429, 400) — o piloto nunca pode sair pior que o Standard.

O modo de falha que mais importa e o TIMEOUT: Flex tem latencia maior, e estourar o
prazo do engine vira retry que ESCALA o L1 pro 3.5-flash (6x o preco do input).
"""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace

os.environ.setdefault("GEMINI_API_KEY", "dummy-test-key")

from google.genai import types  # noqa: E402

from src.api.middleware import GeminiCallTimeoutMiddleware  # noqa: E402
from src.providers import gemini as g  # noqa: E402


def _tier_na_rota(path):
    seen = {}

    async def app(scope, receive, send):
        seen["during"] = g.gemini_service_tier_cv.get()

    async def go():
        await GeminiCallTimeoutMiddleware(app)({"type": "http", "path": path, "headers": []}, None, None)
        return seen["during"], g.gemini_service_tier_cv.get()

    return asyncio.run(go())


def test_so_o_classify_entra_no_flex():
    assert _tier_na_rota("/mov-factsheet/classify") == ("flex", None)  # marcado e resetado
    assert _tier_na_rota("/mov-factsheet/triage") == (None, None)      # fora do piloto


class _Models:
    """Cada item de `roteiro` e o que a N-esima chamada faz: Exception = levanta,
    float = demora esse tanto e responde; roteiro vazio = responde na hora."""

    def __init__(self, roteiro):
        self.roteiro, self.configs = list(roteiro), []

    async def generate_content(self, model, contents, config):
        self.configs.append(config)
        passo = self.roteiro.pop(0) if self.roteiro else None
        if isinstance(passo, Exception):
            raise passo
        if isinstance(passo, float):
            await asyncio.sleep(passo)
        return SimpleNamespace(usage_metadata=SimpleNamespace(traffic_type="ON_DEMAND_FLEX"))


def _gera(roteiro, tier="flex", vertexai=True, timeout_s=10.0):
    models = _Models(roteiro)
    p = g.GeminiProvider.__new__(g.GeminiProvider)
    p._types = types
    p._client = SimpleNamespace(vertexai=vertexai, aio=SimpleNamespace(models=models))

    async def go():
        tok = g.gemini_service_tier_cv.set(tier)
        try:
            return await p._bounded_generate(
                "gemini-3.1-flash-lite", "prompt", types.GenerateContentConfig(temperature=0.0), timeout_s)
        finally:
            g.gemini_service_tier_cv.reset(tok)

    return asyncio.run(go()), [(c.http_options.headers if c.http_options else None) or {} for c in models.configs]


def test_request_flex_manda_os_headers_do_flex_uma_vez_so():
    resp, headers = _gera([])
    assert resp is not None and headers == [g._FLEX_HEADERS]


def test_erro_do_flex_refaz_no_standard_sem_os_headers():
    resp, headers = _gera([RuntimeError("429 RESOURCE_EXHAUSTED")])
    assert resp is not None and headers == [g._FLEX_HEADERS, {}]


def test_flex_lento_estoura_a_fatia_e_o_standard_termina_a_mesma_chamada():
    # prazo 0,2s -> Flex tem 0,1s; ele demoraria 0,3s -> timeout -> Standard responde
    resp, headers = _gera([0.3], timeout_s=0.2)
    assert resp is not None and headers == [g._FLEX_HEADERS, {}]


def test_sem_marca_ou_fora_do_vertex_fica_no_standard():
    assert _gera([], tier=None)[1] == [{}]
    assert _gera([], vertexai=False)[1] == [{}]  # AI Studio nao tem Flex PayGo

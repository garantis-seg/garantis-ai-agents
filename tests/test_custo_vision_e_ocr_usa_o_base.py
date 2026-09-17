"""Vision L1 e PDF-OCR cobram pelo MESMO calculo do caminho texto.

Ate 2026-09-17 `_utils/vision.py::call_vision_l1` e `pdf_ocr/agent.py` tinham uma
formula LOCAL de custo, flat: `prompt_token_count` inteiro a preco de input e so
`candidates_token_count` no output. O caminho texto (`GeminiProvider.agenerate`)
ja cobrava o cacheado no `cached_per_1m` (`test_cached_no_custo.py`) e somava o
thinking ao output (`test_gemini_determinism.py::test_usage_tokens_poe_thinking_no_output`)
— os dois ramos de PDF ficaram de fora dos dois consertos.

Aqui: um usage com cache + thinking, e o custo que sai de cada ramo tem de ser o do
`BaseLLMProvider.calculate_cost` sobre `_usage_tokens` — e DIFERENTE da formula flat
(senao o teste nao distingue o conserto do defeito).
"""
from __future__ import annotations

import asyncio

import pytest
from google.genai import types as gtypes

from src.agents._utils import vision as V
from src.agents.pdf_ocr import agent as ocr_agent
from src.providers.gemini import GEMINI_PRICING, GeminiProvider

_MODELO = "gemini-3.1-flash-lite"
_PROMPT = 1_000_000
_CACHED = 400_000
_CANDIDATES = 10_000
_THOUGHTS = 2_000


class _Usage:
    prompt_token_count = _PROMPT
    cached_content_token_count = _CACHED
    candidates_token_count = _CANDIDATES
    thoughts_token_count = _THOUGHTS


class _Resposta:
    text = "# ok"
    usage_metadata = _Usage()


class _Client:
    def __init__(self) -> None:
        class _Models:
            async def generate_content(self, *, model, contents, config):
                return _Resposta()

        class _Aio:
            models = _Models()

        self.aio = _Aio()


def _provider() -> GeminiProvider:
    """GeminiProvider REAL (preco do catalogo, `calculate_cost` do base.py), sem
    rede: so o client e trocado."""
    p = GeminiProvider.__new__(GeminiProvider)
    p._client = _Client()
    p._types = gtypes
    return p


def _esperado() -> float:
    return round(
        _provider().calculate_cost(_MODELO, _PROMPT, _CANDIDATES + _THOUGHTS, _CACHED), 6
    )


def _formula_flat_antiga() -> float:
    preco = GEMINI_PRICING[_MODELO]
    return round(
        (_PROMPT / 1_000_000) * preco["input_per_1m"]
        + (_CANDIDATES / 1_000_000) * preco["output_per_1m"],
        6,
    )


def test_o_usage_de_prova_DISTINGUE_o_conserto_do_defeito():
    """Controle: se o catalogo nao tiver desconto de cache pro modelo, os dois
    numeros coincidem e os testes abaixo passariam com a formula velha."""
    assert GEMINI_PRICING[_MODELO]["cached_per_1m"] < GEMINI_PRICING[_MODELO]["input_per_1m"]
    assert _esperado() != pytest.approx(_formula_flat_antiga())


def test_vision_l1_cobra_cacheado_e_thinking_pelo_base():
    resp = asyncio.run(V.call_vision_l1(
        _provider(), model=_MODELO, prompt="p", pdf_bytes_list=[b"%PDF-1.4 x"],
    ))

    assert resp.cached_tokens == _CACHED
    assert resp.input_tokens == _PROMPT
    assert resp.output_tokens == _CANDIDATES + _THOUGHTS
    assert resp.metadata["cost_usd"] == pytest.approx(_esperado())
    assert resp.metadata["cost_usd"] != pytest.approx(_formula_flat_antiga())


def test_pdf_ocr_cobra_cacheado_e_thinking_pelo_base(monkeypatch):
    monkeypatch.setattr(
        ocr_agent.LLMFactory, "create_provider", staticmethod(lambda *_a, **_k: _provider())
    )

    out = asyncio.run(ocr_agent.convert_pdf_to_markdown(b"%PDF-1.4 x", model=_MODELO))

    assert out.success, out.error
    assert out.total_input_tokens == _PROMPT
    assert out.total_output_tokens == _CANDIDATES + _THOUGHTS
    assert out.cost_usd == pytest.approx(_esperado())
    assert out.cost_usd != pytest.approx(_formula_flat_antiga())

"""Tests de determinismo do GeminiProvider (Bug 4 handoff).

Cobre o helper _build_config_params que centraliza:
  - temperature=0 -> top_p=1.0, top_k=1 (greedy strict decoding)
  - thinking_budget=0 em gemini-2.5-* (desabilita thinking mode)
  - thinking_budget ignorado em gemini-1.x/2.0 (nao tem thinking)
  - seed opcional (passa direto se SDK aceita)

Validacao prod e via cascade m=3 — 3 runs consecutivos com mesmo input
devem produzir L2/L3 parsed_card_hash IDENTICOS.
"""
from __future__ import annotations

import os

import pytest


# Garante api_key dummy p/ instanciacao
os.environ.setdefault("GEMINI_API_KEY", "dummy-test-key")


class _FakeTypes:
    """Stub do google.genai.types p/ teste sem SDK ativo."""

    class GenerateContentConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class ThinkingConfig:
        def __init__(self, **kw):
            self.kw = kw

        def __repr__(self):
            return f"ThinkingConfig({self.kw})"


@pytest.fixture
def provider():
    """Provider mockado sem chamar genai.Client.__init__."""
    from src.providers.gemini import GeminiProvider

    p = GeminiProvider.__new__(GeminiProvider)
    p._types = _FakeTypes
    p._default_model = "gemini-2.5-flash-lite"
    return p


# ── temperature=0 → top_p=1.0, top_k=1 (greedy strict) ─────────────────────


def test_temperature_zero_forces_top_p_one(provider):
    cp = provider._build_config_params(
        temperature=0.0, max_tokens=100, response_schema=None,
        model="gemini-2.5-flash",
    )
    assert cp["top_p"] == 1.0
    assert cp["top_k"] == 1


def test_temperature_zero_top_p_override_respected(provider):
    """Caller pode overridar via kwargs."""
    cp = provider._build_config_params(
        temperature=0.0, max_tokens=100, response_schema=None,
        model="gemini-2.5-flash",
        top_p=0.95, top_k=10,
    )
    assert cp["top_p"] == 0.95
    assert cp["top_k"] == 10


def test_temperature_nonzero_no_auto_top_p_top_k(provider):
    """temperature > 0 nao forca top_p/k automaticamente — preserva default SDK."""
    cp = provider._build_config_params(
        temperature=0.5, max_tokens=100, response_schema=None,
        model="gemini-2.5-flash",
    )
    assert "top_p" not in cp
    assert "top_k" not in cp


def test_temperature_nonzero_explicit_top_p_passed(provider):
    """temperature > 0 com top_p explicit ainda passa."""
    cp = provider._build_config_params(
        temperature=0.5, max_tokens=100, response_schema=None,
        model="gemini-2.5-flash",
        top_p=0.8,
    )
    assert cp["top_p"] == 0.8


# ── thinking_budget (Gemini 2.5 only) ──────────────────────────────────────


def test_thinking_budget_zero_in_gemini_25(provider):
    """gemini-2.5-* + thinking_budget=0 -> ThinkingConfig na config."""
    cp = provider._build_config_params(
        temperature=0.0, max_tokens=100, response_schema=None,
        model="gemini-2.5-flash",
        thinking_budget=0,
    )
    assert "thinking_config" in cp
    assert cp["thinking_config"].kw == {"thinking_budget": 0}


def test_thinking_budget_zero_in_gemini_25_lite(provider):
    cp = provider._build_config_params(
        temperature=0.0, max_tokens=100, response_schema=None,
        model="gemini-2.5-flash-lite",
        thinking_budget=0,
    )
    assert "thinking_config" in cp


def test_thinking_budget_ignored_in_gemini_15(provider):
    """gemini-1.5-* nao tem thinking mode — ignora kwarg."""
    cp = provider._build_config_params(
        temperature=0.0, max_tokens=100, response_schema=None,
        model="gemini-1.5-flash",
        thinking_budget=0,
    )
    assert "thinking_config" not in cp


def test_thinking_budget_ignored_in_gemini_20(provider):
    """gemini-2.0-* (sem thinking) ignora kwarg."""
    cp = provider._build_config_params(
        temperature=0.0, max_tokens=100, response_schema=None,
        model="gemini-2.0-flash",
        thinking_budget=0,
    )
    assert "thinking_config" not in cp


def test_thinking_budget_absent_no_thinking_config(provider):
    """Sem kwarg explicito — preserva default SDK (no override)."""
    cp = provider._build_config_params(
        temperature=0.0, max_tokens=100, response_schema=None,
        model="gemini-2.5-flash",
    )
    assert "thinking_config" not in cp


def test_thinking_budget_positive_value_passed(provider):
    """thinking_budget>0 (manter thinking ativo com budget customizado) passa."""
    cp = provider._build_config_params(
        temperature=0.0, max_tokens=100, response_schema=None,
        model="gemini-2.5-flash",
        thinking_budget=1024,
    )
    assert "thinking_config" in cp
    assert cp["thinking_config"].kw == {"thinking_budget": 1024}


# ── seed (opt-in) ──────────────────────────────────────────────────────────


def test_seed_passed_when_provided(provider):
    cp = provider._build_config_params(
        temperature=0.0, max_tokens=100, response_schema=None,
        model="gemini-2.5-flash",
        seed=42,
    )
    assert cp["seed"] == 42


def test_seed_absent_no_key(provider):
    cp = provider._build_config_params(
        temperature=0.0, max_tokens=100, response_schema=None,
        model="gemini-2.5-flash",
    )
    assert "seed" not in cp


# ── response_schema vs response_mime_type ─────────────────────────────────


def test_response_schema_sets_mime_type(provider):
    from pydantic import BaseModel

    class _S(BaseModel):
        x: str = ""

    cp = provider._build_config_params(
        temperature=0.0, max_tokens=100, response_schema=_S,
        model="gemini-2.5-flash",
    )
    assert cp["response_mime_type"] == "application/json"
    assert cp["response_schema"] is _S


def test_response_mime_type_only_when_schema_none(provider):
    """Caller passa response_mime_type quando schema rejeitado pelo SDK
    (ex: processo_synthesis L2 — Gemini rejeita dict[str,Any] additionalProps)."""
    cp = provider._build_config_params(
        temperature=0.0, max_tokens=100, response_schema=None,
        model="gemini-2.5-flash",
        response_mime_type="application/json",
    )
    assert cp["response_mime_type"] == "application/json"
    assert "response_schema" not in cp


# ── Agent integration smoke ────────────────────────────────────────────────


def test_agents_pass_thinking_budget_zero():
    """Sanidade: os 3 agents criticos passam thinking_budget=0 e temperature=0.0.
    Confirma fix do Bug 4 cobre toda a cascade.

    ⚠️ 2026-07-26: o commit 9425766 (2026-05-28) EXTRAIU a chamada do L1 do
    mov_factsheet pro helper `_utils/vision.py::call_l1_with_vision_fallback`, e a
    `temperature=0.0` desceu junto (vision.py:356 ramo vision, :375 ramo text). O
    assert original olhava so o fonte do AGENT, entao passou a acusar regressao onde
    nao havia — medido no boundary do SDK, o `GenerateContentConfig` do L1 sai com
    `temperature=0.0` nos DOIS ramos. Guard intacto; o teste e que ficou pra tras.

    ⛔ NAO "consertar" concatenando o fonte do helper em `src_text` antes dos dois
    asserts: o helper contem AS DUAS strings, entao os dois viram tautologia SO pro
    mov (o unico que usa o helper) — medido por mutacao, essa versao deixa passar
    `thinking_budget=8192` no agent E `temperature=0.7` no helper.
    `thinking_budget` continua cobrado NO AGENT (o helper so tem default, nao
    substitui o call site); a temperature do helper e cobrada em TODAS as
    ocorrencias, senao um ramo mutado se esconde atras do outro intacto.
    """
    import inspect
    import re

    from src.agents._utils import vision as vision_helper
    from src.agents.mov_factsheet import agent as mov_agent
    from src.agents.processo_synthesis import agent as ps_agent
    from src.agents.merito_synthesis import agent as ms_agent

    helper_text = inspect.getsource(vision_helper)

    for mod in (mov_agent, ps_agent, ms_agent):
        src_text = inspect.getsource(mod)
        assert "thinking_budget=0" in src_text, (
            f"{mod.__name__} nao passa thinking_budget=0 — non-determinismo "
            "L2/L3 vai reaparecer."
        )
        if "call_l1_with_vision_fallback" in src_text:
            temps = re.findall(r"temperature=([0-9.]+)", helper_text)
            assert temps and all(t == "0.0" for t in temps), (
                f"{mod.__name__}: helper call_l1_with_vision_fallback com "
                f"temperature != 0.0 — non-determinismo. Achado: {temps}"
            )
        else:
            assert "temperature=0.0" in src_text, (
                f"{mod.__name__} usa temperature != 0.0 — non-determinismo."
            )


# ── L3 previous_snapshot fora do prompt (v2.7.3, 2026-07-02) ────────────────
# Supersede os testes de truncation do Bug 4: o bloco SNAPSHOT ANTERIOR foi
# REMOVIDO por inteiro (ancora + quebrava o seed deterministico entre cascades
# — o seed_for inclui o prompt, e o snapshot anterior mudava a cada cascade).
# A propriedade que os testes antigos perseguiam (prompt identico entre
# cascades) agora vale TOTALMENTE: previous_snapshot nao influencia o prompt.


def test_l3_prompt_invariante_a_previous_snapshot():
    """Acceptance do fix C (frescor/convergencia): o prompt L3 e BYTE-IDENTICO
    com previous_snapshot presente, ausente ou variando — seed estavel entre
    cascades reais."""
    from src.agents.merito_synthesis.prompts import build_merito_synthesis_prompt
    from src.agents.merito_synthesis.schemas import (
        MeritoSynthesisRequest,
        PreviousSnapshot,
        ProcessoSynthesisMin,
    )

    ps = [ProcessoSynthesisMin(
        processo_numero="0000000-00.0000.0.00.0000", tipo_judicial="fiscal",
    )]
    base = MeritoSynthesisRequest(merito_id=1, processo_syntheses=ps)
    com_prev = MeritoSynthesisRequest(
        merito_id=1, processo_syntheses=ps,
        previous_snapshot=PreviousSnapshot(
            risco_anterior="Altissimo",
            classified_at_anterior="2026-05-23 10:35:26.937755",
            decisao_anterior={"natureza": "improcedente"},
        ),
    )
    com_prev2 = MeritoSynthesisRequest(
        merito_id=1, processo_syntheses=ps,
        previous_snapshot=PreviousSnapshot(
            risco_anterior="Baixo",
            classified_at_anterior="2026-07-01 08:00:00.000000",
        ),
    )

    p_base = build_merito_synthesis_prompt(base)
    assert p_base == build_merito_synthesis_prompt(com_prev)
    assert p_base == build_merito_synthesis_prompt(com_prev2)
    # O bloco morreu de verdade (nem o header sobra)
    assert "SNAPSHOT ANTERIOR" not in p_base
    assert "risco_anterior" not in p_base

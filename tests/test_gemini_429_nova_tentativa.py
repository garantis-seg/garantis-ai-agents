"""Nova tentativa depois do 429 do Vertex (18/11/2026, loop de fichas, rodada 8).

Com a fila de fichas a 24, o redator recebeu "429 RESOURCE_EXHAUSTED" e 4 fichas de 82
morreram no `redigir_v4_step`. O provedor agora espera e tenta de novo, só no 429.
"""
import asyncio
from types import SimpleNamespace

import pytest

import src.providers.gemini as g


class Erro429(Exception):
    code = 429


def _resposta():
    cand = SimpleNamespace(finish_reason=SimpleNamespace(name="STOP"), safety_ratings=None)
    return SimpleNamespace(text='{"ok":1}', candidates=[cand], prompt_feedback=None,
                           usage_metadata=None)


def _provedor(erros):
    """Provedor com cliente falso: levanta os `erros` em ordem e depois responde."""
    chamadas = []

    async def generate_content(**_):
        chamadas.append(1)
        if erros:
            raise erros.pop(0)
        return _resposta()

    p = object.__new__(g.GeminiProvider)
    p._client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content)))
    p._types = SimpleNamespace(GenerateContentConfig=lambda **kw: kw)
    p._default_model = "m"
    p._build_config_params = lambda **kw: {}
    p.calculate_cost = lambda *a: 0.0
    return p, chamadas


@pytest.fixture(autouse=True)
def _sem_espera(monkeypatch):
    async def nada(*a, **k):
        return None
    monkeypatch.setattr(g, "_ESPERAS_APOS_429_S", (0.0, 0.0))
    monkeypatch.setattr(g._gemini_rate_limiter, "acquire", nada)
    monkeypatch.setattr(g._gemini_tpm_limiter, "acquire", nada)


def test_o_429_volta_ao_laco_e_a_chamada_responde():
    p, chamadas = _provedor([Erro429("429 RESOURCE_EXHAUSTED")])
    r = asyncio.run(p.agenerate("oi", model="m"))
    assert r.text == '{"ok":1}' and len(chamadas) == 2


def test_o_429_que_nao_passa_sobe_depois_das_esperas():
    p, chamadas = _provedor([Erro429("a"), Erro429("b"), Erro429("c")])
    with pytest.raises(Erro429):
        asyncio.run(p.agenerate("oi", model="m"))
    assert len(chamadas) == 3


def test_outro_erro_sobe_na_hora():
    p, chamadas = _provedor([ValueError("400 INVALID_ARGUMENT")])
    with pytest.raises(ValueError):
        asyncio.run(p.agenerate("oi", model="m"))
    assert len(chamadas) == 1


def test_com_prazo_do_engine_nao_ha_espera():
    p, chamadas = _provedor([Erro429("a")])
    tok = g.gemini_call_timeout_cv.set(30.0)
    try:
        with pytest.raises(Erro429):
            asyncio.run(p.agenerate("oi", model="m"))
    finally:
        g.gemini_call_timeout_cv.reset(tok)
    assert len(chamadas) == 1

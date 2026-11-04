"""R13: os agentes da ficha chamam o Gemini com a amostragem no padrão do modelo.

O Google pede isso no Gemini 3: temperature, top_p e top_k ficam no padrão.
Temperature baixa pode causar laço e piorar o raciocínio. Os agentes da ficha
passam `temperature=None` e não passam `seed`. O provider então omite os 4
campos. O determinismo da ficha vem das regras e dos validadores.

O que este arquivo cobra:

1. O provider omite temperature, top_p, top_k e seed com `temperature=None`.
2. O `call_vision_l1` (o caminho do OCR) faz o mesmo no config do SDK.
3. Cada agente da ficha chama o provider sem temperature e sem seed.
4. Um gate de fonte (AST) varre as chamadas dos módulos da ficha.

Controle positivo: um agente fora da ficha (a triagem) ainda manda
`temperature=0.0`, o provider ainda monta greedy e seed com `temperature=0`, e
o gate de fonte acha a temperature fixa num módulo fora da ficha.
"""
from __future__ import annotations

import ast
import asyncio
import inspect
import json
import os
from types import SimpleNamespace

import pytest
from google.genai import types as gtypes

os.environ.setdefault("GEMINI_API_KEY", "dummy-test-key")

from src.agents._utils import vision as V  # noqa: E402
from tests.test_l1_seed_deterministico import _ProviderQueCaptura  # noqa: E402

_AMOSTRAGEM = ("temperature", "top_p", "top_k", "seed")


# ── 1. provider ──────────────────────────────────────────────────────────────


class _Types:
    class GenerateContentConfig:
        def __init__(self, **kw):
            self.kwargs = kw

    class ThinkingConfig:
        def __init__(self, **kw):
            self.kw = kw


@pytest.fixture
def provider():
    from src.providers.gemini import GeminiProvider

    p = GeminiProvider.__new__(GeminiProvider)
    p._types = _Types
    p._default_model = "gemini-3.5-flash"
    return p


def test_provider_none_omite_temperature_top_p_top_k_e_seed(provider):
    cp = provider._build_config_params(
        temperature=None, max_tokens=100, response_schema=None, model="gemini-3.5-flash",
        seed=42, top_p=0.5, top_k=3, thinking_budget=0,
        response_mime_type="application/json",
    )
    for campo in _AMOSTRAGEM:
        assert campo not in cp, campo
    # o resto da chamada continua igual
    assert cp["max_output_tokens"] == 100
    assert cp["response_mime_type"] == "application/json"
    assert "thinking_config" in cp


def test_controle_provider_com_temperature_zero_ainda_manda_greedy_e_seed(provider):
    cp = provider._build_config_params(
        temperature=0.0, max_tokens=100, response_schema=None, model="gemini-3.5-flash",
        seed=42,
    )
    assert cp["temperature"] == 0.0
    assert cp["top_p"] == 1.0 and cp["top_k"] == 1
    assert cp["seed"] == 42


# ── 2. call_vision_l1 (config montado à mão) ────────────────────────────────


def test_call_vision_l1_none_omite_temperature_e_seed_no_config_do_sdk():
    prov = _ProviderQueCaptura()
    asyncio.run(V.call_vision_l1(
        prov, model="m", prompt="p", pdf_bytes_list=[b"%PDF-1.4 fake"],
        temperature=None, seed=4242,
    ))
    [config] = prov._client.configs
    assert config.temperature is None
    assert config.seed is None


def test_controle_call_vision_l1_default_ainda_manda_temperature_e_seed():
    prov = _ProviderQueCaptura()
    asyncio.run(V.call_vision_l1(
        prov, model="m", prompt="p", pdf_bytes_list=[b"%PDF-1.4 fake"], seed=4242,
    ))
    [config] = prov._client.configs
    assert config.temperature == 0.0
    assert config.seed == 4242
    assert isinstance(config, gtypes.GenerateContentConfig)


# ── 3. cada agente da ficha, de ponta a ponta ───────────────────────────────


def _sem_amostragem(chamadas: list[dict]) -> None:
    assert chamadas, "o agente não chamou o provider"
    for kw in chamadas:
        assert "temperature" in kw and kw["temperature"] is None, kw.get("temperature")
        assert "seed" not in kw
        assert "top_p" not in kw and "top_k" not in kw


def test_redator_v5_fases_a_e_b_sem_amostragem(monkeypatch):
    from tests import test_ficha_writer_v5 as T

    prov = T._Prov(T._leituras(), [T._emissao()])
    r = T._rodar(prov, monkeypatch)
    assert r.success, r.erros
    assert {c["_fase"] for c in prov.chamadas} == {"A", "B"}
    _sem_amostragem(prov.chamadas)


def test_auditor_v3_fases_a_e_b_sem_amostragem(monkeypatch):
    from tests import test_auditor_ficha_v3 as T

    prov = T._Prov(T._ler_recurso(), [T._saida()])
    r = T._rodar(prov, monkeypatch)
    assert r.success
    assert {c["_fase"] for c in prov.chamadas} == {"A", "B"}
    _sem_amostragem(prov.chamadas)


def test_qualificador_conexo_fases_a_b_e_auditor_sem_amostragem(monkeypatch):
    from tests import test_qualificador_conexo as T

    prov = T._Prov(T._leituras_padrao(), [T._emissao_valida()], [T._SUSTENTA])
    r = T._rodar(prov, monkeypatch)
    assert r.auditado
    assert {c["_fase"] for c in prov.chamadas} == {"A", "B", "auditor"}
    _sem_amostragem(prov.chamadas)


def test_ocr_do_doc_indexer_sem_amostragem(monkeypatch):
    from src.agents.doc_indexer import ocr as O
    from tests.test_doc_indexer import pdf_misto

    chamadas: list[dict] = []

    async def _vision(provider, **kw):
        chamadas.append(kw)
        return SimpleNamespace(text=json.dumps({"paginas": []}), model="m",
                               metadata={"cost_usd": 0.0}, input_tokens=0)

    monkeypatch.setattr(V, "call_vision_l1", _vision)
    asyncio.run(O.ocr_paginas(object(), pdf_misto(), [2]))
    _sem_amostragem(chamadas)


def test_controle_triagem_fora_da_ficha_ainda_manda_temperature_zero(monkeypatch):
    import src.agents.mov_triage.agent as triagem

    chamadas: list[dict] = []

    class _Prov:
        async def agenerate(self, **kw):
            chamadas.append(kw)
            return SimpleNamespace(
                text=json.dumps({"resumo_ato": "x", "tipo_doc": "peticao",
                                 "mov_merito": False, "mov_garantia_exec": False}),
                input_tokens=1, output_tokens=1, cached_tokens=0, metadata={},
            )

    monkeypatch.setattr(triagem, "create_provider", lambda p: _Prov())
    asyncio.run(triagem.classify_mov_triage(
        processo={"cnj": "0"},
        mov={"mov_id": "m-1", "data": "2024-01-01", "texto": "Juntada de peticao."},
    ))
    [kw] = chamadas
    assert kw["temperature"] == 0.0


# ── 4. gate de fonte: toda chamada ao modelo nos módulos da ficha ───────────

_CHAMADAS_AO_MODELO = {"agenerate", "generate", "call_vision_l1"}


def _modulos_da_ficha():
    from src.agents.auditor_ficha import agent as auditor_v2
    from src.agents.auditor_ficha import agent_v3 as auditor_v3
    from src.agents.doc_indexer import ocr
    from src.agents.ficha_writer import agent as writer
    from src.agents.ficha_writer import agent_v5 as writer_v5
    from src.agents.ficha_writer import fase_a_nativa
    from src.agents.ficha_writer import ferramentas
    from src.agents.qualificador_conexo import agent as qualificador
    from src.agents.qualificador_conexo import auditor as qualificador_auditor

    return [writer, writer_v5, ferramentas, fase_a_nativa, auditor_v2, auditor_v3,
            qualificador, qualificador_auditor, ocr]


def _chamadas(mod) -> list[ast.Call]:
    arvore = ast.parse(inspect.getsource(mod))
    out = []
    for no in ast.walk(arvore):
        if not isinstance(no, ast.Call):
            continue
        nome = (no.func.attr if isinstance(no.func, ast.Attribute)
                else getattr(no.func, "id", None))
        if nome in _CHAMADAS_AO_MODELO:
            out.append(no)
    return out


def _problemas(mod) -> list[str]:
    erros = []
    for call in _chamadas(mod):
        kws = {k.arg: k.value for k in call.keywords}
        temp = kws.get("temperature")
        if not (isinstance(temp, ast.Constant) and temp.value is None):
            erros.append(f"{mod.__name__}:{call.lineno} sem temperature=None")
        for campo in ("seed", "top_p", "top_k"):
            if campo in kws:
                erros.append(f"{mod.__name__}:{call.lineno} passa {campo}")
    return erros


def test_gate_modulos_da_ficha_chamam_o_modelo_no_padrao():
    total = 0
    for mod in _modulos_da_ficha():
        total += len(_chamadas(mod))
        assert _problemas(mod) == []
    # 1 writer v3/v4 + 1 v5 + 1 navegar + 1 auditor v2 + 1 v3 + 2 qualificador
    # + 1 auditor do qualificador + 1 OCR. Menos que isso = o gate ficou cego.
    assert total >= 9, total


def test_controle_gate_acha_temperature_fixa_fora_da_ficha():
    import src.agents.mov_triage.agent as triagem

    assert _chamadas(triagem), "o gate não achou a chamada da triagem"
    assert any("sem temperature=None" in e for e in _problemas(triagem))

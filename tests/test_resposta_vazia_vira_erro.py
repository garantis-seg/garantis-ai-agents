"""A resposta VAZIA do LLM vira erro do L1, como o JSON quebrado.

Antes, ela virava um card 'ruido' com resumo fixo, que afirmava relevancia sem leitura. Agora
o card sai com `error`, e a rota devolve 500. O `call` do garantis-shared trata o 500 como o
parse-fail de sempre: tenta de novo e, sem sucesso, conta o mov como falho (`l1_degraded`).
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import src.agents.mov_factsheet.agent as l1

MOV = {"mov_id": "m-1", "data": "2024-01-01", "texto": "Juntada de peticao da executada. " * 4}


@pytest.fixture()
def resposta_vazia(monkeypatch):
    async def _chamada(provider, **kw):
        return SimpleNamespace(text="", input_tokens=900, output_tokens=0, cached_tokens=0,
                               metadata={"model_variant": "text", "finish_reason": "SAFETY"})

    monkeypatch.setattr(l1, "call_l1_with_vision_fallback", _chamada)
    monkeypatch.setattr(l1, "create_provider", lambda p: object())
    monkeypatch.setenv("L1_NEUTRAL_ENABLED", "true")


@pytest.mark.parametrize("classe", [None, "peticao"])
def test_resposta_vazia_vira_card_de_erro(resposta_vazia, classe):
    out = asyncio.run(l1.classify_mov_factsheet(processo={"cnj": "0"}, mov=MOV, classe=classe))
    assert out["card"]["error"] == repr(ValueError("empty LLM response"))
    assert "relevancia_merito" not in out["card"]
    # A chamada paga fica registrada.
    assert out["usage"]["input_tokens"] == 900


def test_a_rota_devolve_500_como_no_parse_fail(resposta_vazia):
    from src.api.routes.mov_factsheet import router
    app = FastAPI()
    app.include_router(router)
    resp = TestClient(app).post("/mov-factsheet/classify", json={
        "processo": {"cnj": "0"}, "mov": MOV,
    })
    assert resp.status_code == 500
    assert "empty LLM response" in resp.json()["detail"]

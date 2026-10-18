"""A triagem malformada do L1 vai direto ao passe completo, sem 500 e sem retry.

O `call` do garantis-shared repete o 5xx ate 6 vezes. Um card que nao parseia nao melhora
com outra chamada: a rota devolve 200 com `card` null, e o materializer roda o completo
(`precisa_completo(None)` -> True). O teste cruza os 2 lados do contrato: a rota real pelo
TestClient e o roteador real do shared.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import src.agents.mov_triage.agent as triage_mod
from garantis_shared.engine_v6.layer1_mov_factsheet.triage import precisa_completo


class _Fake:
    def __init__(self, texto: str):
        self.texto = texto
        self.chamadas = 0

    async def agenerate(self, **kwargs):
        self.chamadas += 1
        return SimpleNamespace(
            text=self.texto, model=kwargs.get("model"),
            input_tokens=900, output_tokens=40, cached_tokens=0,
            metadata={"cost_usd": 0.0001, "provider": "gemini"},
        )


@pytest.fixture()
def client() -> TestClient:
    from src.api.routes.mov_factsheet import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _post(client, monkeypatch, texto: str):
    fake = _Fake(texto)
    monkeypatch.setattr(triage_mod, "create_provider", lambda *_a, **_k: fake)
    resp = client.post("/mov-factsheet/triage", json={
        "processo": {"cnj": "0001234-56.2020.4.02.5101"},
        "mov": {"mov_id": "m-1", "texto": "Juntada de peticao"},
    })
    return resp, fake


def test_card_malformado_volta_200_com_card_null_e_o_caller_roda_o_completo(client, monkeypatch):
    resp, fake = _post(client, monkeypatch, "isto nao e json")

    assert resp.status_code == 200
    body = resp.json()
    assert body["card"] is None
    assert precisa_completo(body["card"]) is True
    # A chamada paga fica registrada: o shared grava usage e a resposta bruta.
    assert body["raw_response"] == "isto nao e json"
    assert body["usage"]["output_tokens"] == 40
    assert fake.chamadas == 1


def test_card_valido_segue_igual(client, monkeypatch):
    card = {"resumo_ato": "Juntada de peticao.", "tipo_doc": "peticao",
            "mov_merito": False, "mov_garantia_exec": False}
    resp, _ = _post(client, monkeypatch, json.dumps(card))

    assert resp.status_code == 200
    assert resp.json()["card"]["mov_merito"] is False
    assert precisa_completo(resp.json()["card"]) is False

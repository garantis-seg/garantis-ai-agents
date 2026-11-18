"""A rota `/leitura/executar`: a porta de entrada e saída do núcleo `garantis_shared.leitura`.

A rota não sabe nada de ficha. Recebe o pedido e o schema, chama o modelo e devolve a
resposta crua com o uso. Os testes não chamam LLM.
"""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routes import leitura as rota


@pytest.fixture
def cliente(monkeypatch):
    chamadas: list[dict] = []
    estado = {"texto": '{"estado": {"valor": "RE_ADMITIDO", "prova": ["3"]}, "justificativa": "x"}',
              "falha": None}

    class _Provedor:
        async def agenerate(self, prompt, **kw):
            chamadas.append({"prompt": prompt, **kw})
            if estado["falha"]:
                raise estado["falha"]
            return SimpleNamespace(text=estado["texto"], model=kw["model"], input_tokens=100,
                                   output_tokens=20, metadata={"cost_usd": 0.0123})

    monkeypatch.setattr(rota, "create_provider", lambda _nome: _Provedor())
    app = FastAPI()
    app.include_router(rota.router)
    return TestClient(app), chamadas, estado


_CORPO = {"pedido": "leia os andamentos", "schema": {"type": "OBJECT", "properties": {}},
          "modelo": "gemini-4-argon", "pergunta": "timeline_carf_v2"}


def test_devolve_a_resposta_crua_e_o_uso(cliente):
    cli, chamadas, _ = cliente
    r = cli.post("/leitura/executar", json=_CORPO)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["resposta"]["estado"] == {"valor": "RE_ADMITIDO", "prova": ["3"]} and d["erro"] is None
    assert d["uso"] == {"entrada": 100, "saida": 20, "custo_usd": 0.0123, "modelo": "gemini-4-argon"}
    c = chamadas[0]
    assert c["prompt"] == "leia os andamentos" and c["response_schema"] == _CORPO["schema"]
    assert c["temperature"] == 0.0 and "thinking_budget" not in c, "o argon recusa thinking_config"


def test_o_raciocinio_so_vai_quando_pedido(cliente):
    cli, chamadas, _ = cliente
    cli.post("/leitura/executar", json={**_CORPO, "modelo": "gemini-3.1-pro-preview",
                                         "params": {"pensar": 8000, "temp": None}})
    assert chamadas[0]["thinking_budget"] == 8000 and chamadas[0]["temperature"] is None


def test_json_invalido_volta_200_com_o_erro_e_o_texto(cliente):
    """Quem chama (o núcleo) decide: a leitura degrada para a regra, e o texto fica no registro."""
    cli, _, estado = cliente
    estado["texto"] = "isto não é json"
    d = cli.post("/leitura/executar", json=_CORPO).json()
    assert d["resposta"] is None and d["erro"].startswith("json_invalido") and d["texto"] == "isto não é json"


def test_modelo_fora_do_catalogo_e_422_e_falha_do_provedor_e_500(cliente):
    cli, chamadas, estado = cliente
    assert cli.post("/leitura/executar", json={**_CORPO, "modelo": "modelo-inventado"}).status_code == 422
    assert chamadas == []
    estado["falha"] = TimeoutError("o modelo não respondeu")
    assert cli.post("/leitura/executar", json=_CORPO).status_code == 500

"""ficha_writer — testa o prompt (deterministico), a validacao de shape/tipo do
agent (com provider MOCKADO) e a rota (mount isolado do router). NAO chama LLM.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import src.agents.ficha_writer.agent as agent_mod
from src.agents.ficha_writer import write_ficha_fields
from src.agents.ficha_writer.prompts import build_write_fields_prompt
from src.agents.ficha_writer.schemas import (
    CampoComErro,
    CampoSpec,
    FichaWriteFieldsRequest,
)
from src.api.routes.ficha_writer import router


# ── Fixtures / helpers ─────────────────────────────────────────────────────


class _FakeProvider:
    """Provider fake: devolve `text` fixo + metadata sem chamar LLM.

    Captura os kwargs da ultima call (p/ assertar JSON mode / temperature).
    """

    def __init__(self, text: str, cost: float = 0.0123, model_out: str = "gemini-2.5-flash"):
        self._text = text
        self._cost = cost
        self._model_out = model_out
        self.last_kwargs: dict = {}

    async def agenerate(self, **kwargs):
        self.last_kwargs = kwargs
        return SimpleNamespace(
            text=self._text,
            model=self._model_out,
            input_tokens=100,
            output_tokens=40,
            metadata={"cost_usd": self._cost, "provider": "gemini"},
        )


def _campos() -> list[CampoSpec]:
    return [
        CampoSpec(nome="resumo", tipo="string", limite_chars=120,
                  guidance="1 frase sobre o estado do caso.",
                  exemplos=["Execucao fiscal em fase de garantia."]),
        CampoSpec(nome="pontos", tipo="array_string", limite_chars=80, quantidade=2,
                  guidance="Bullets de risco."),
        CampoSpec(nome="par", tipo="objeto_p1_p2", limite_chars=200,
                  guidance="Dois paragrafos."),
    ]


def _req(campos=None, campos_com_erro=None) -> FichaWriteFieldsRequest:
    return FichaWriteFieldsRequest(
        dossie={"razao_social": "ACME LTDA", "processo": "0001234-56.2020.8.26.0100",
                "temperatura": "morna", "ultima_posicao": "12/06"},
        campos=campos if campos is not None else _campos(),
        campos_com_erro=campos_com_erro,
    )


def _good_payload() -> str:
    return json.dumps({
        "resumo": "Execucao fiscal com garantia apresentada.",
        "pontos": ["Decisao de 1o grau desfavoravel.", "Recurso pendente."],
        "par": {"p1": "Primeiro paragrafo.", "p2": "Segundo paragrafo."},
    }, ensure_ascii=False)


def _install(monkeypatch, provider) -> _FakeProvider:
    monkeypatch.setattr(agent_mod, "create_provider", lambda p: provider)
    return provider


# ── Prompt (deterministico) ────────────────────────────────────────────────


def test_prompt_carries_persona_dossie_campos_and_rules():
    p = build_write_fields_prompt(_req())
    assert "SUBSCRITOR SENIOR" in p
    assert "como voce sabe disso?" in p
    assert "ACME LTDA" in p and "0001234-56.2020.8.26.0100" in p  # dossie serializado
    # cada campo pedido aparece com nome + limite
    assert '"resumo"' in p and "120 chars" in p
    assert '"pontos"' in p and "2 itens" in p
    assert '"par"' in p and '{"p1"' in p
    # <regras_de_redacao> por ULTIMO (recency anchor)
    assert "<regras_de_redacao>" in p
    assert p.rstrip().endswith("</regras_de_redacao>")


def test_prompt_embeds_the_nevers():
    p = build_write_fields_prompt(_req())
    # normaliza whitespace (as regras quebram linha no meio das frases)
    flat = " ".join(p.lower().split())
    for termo in ("apolice nao identificada", "watchlist", "snapshot", "engine",
                  "ultima posicao disponivel", "restricao dura"):
        assert termo in flat, termo


def test_prompt_retry_block_present_only_on_retry():
    assert "CORRECAO OBRIGATORIA" not in build_write_fields_prompt(_req())
    req = _req(campos_com_erro=[
        CampoComErro(nome="resumo", erro="estourou limite: 142/120 chars",
                     valor_anterior="texto longo demais que passou do limite ..."),
    ])
    p = build_write_fields_prompt(req)
    assert "CORRECAO OBRIGATORIA" in p
    assert "estourou limite: 142/120 chars" in p
    assert '"resumo"' in p
    # retry vem ANTES das regras (regras seguem sendo o ultimo bloco)
    assert p.index("CORRECAO OBRIGATORIA") < p.index("<regras_de_redacao>")


# ── Agent: happy path ──────────────────────────────────────────────────────


def test_happy_path_returns_all_fields_and_cost(monkeypatch):
    prov = _install(monkeypatch, _FakeProvider(_good_payload(), cost=0.0123))
    out = asyncio.run(write_ficha_fields(_req()))
    assert out.success is True
    assert out.error is None
    assert set(out.campos.keys()) == {"resumo", "pontos", "par"}
    assert out.campos["pontos"] == ["Decisao de 1o grau desfavoravel.", "Recurso pendente."]
    assert out.campos["par"] == {"p1": "Primeiro paragrafo.", "p2": "Segundo paragrafo."}
    assert out.cost_usd == 0.0123
    assert out.model == "gemini-2.5-flash"
    # JSON mode SEM schema estatico + determinismo
    assert prov.last_kwargs.get("response_mime_type") == "application/json"
    assert prov.last_kwargs.get("response_schema") is None
    assert prov.last_kwargs.get("temperature") == 0.0


# ── Agent: campo faltando / tipo errado -> success=false ───────────────────


def test_missing_field_fails_softly(monkeypatch):
    payload = json.dumps({"resumo": "ok", "pontos": ["a", "b"]})  # falta "par"
    _install(monkeypatch, _FakeProvider(payload))
    out = asyncio.run(write_ficha_fields(_req()))
    assert out.success is False
    assert out.campos == {}
    assert "par" in out.error and "ausente" in out.error


def test_wrong_type_fails_softly(monkeypatch):
    # "pontos" deveria ser lista de strings, veio string
    payload = json.dumps({"resumo": "ok", "pontos": "nao e lista",
                          "par": {"p1": "a", "p2": "b"}})
    _install(monkeypatch, _FakeProvider(payload))
    out = asyncio.run(write_ficha_fields(_req()))
    assert out.success is False
    assert "pontos" in out.error


def test_objeto_p1_p2_missing_part_fails(monkeypatch):
    payload = json.dumps({"resumo": "ok", "pontos": ["a", "b"],
                          "par": {"p1": "so p1"}})  # falta p2
    _install(monkeypatch, _FakeProvider(payload))
    out = asyncio.run(write_ficha_fields(_req()))
    assert out.success is False
    assert "par" in out.error


def test_parse_fail_reports_cost_and_model(monkeypatch):
    _install(monkeypatch, _FakeProvider("nao e json {{{", cost=0.005))
    out = asyncio.run(write_ficha_fields(_req()))
    assert out.success is False
    assert out.campos == {}
    assert "parse" in out.error.lower()
    assert out.cost_usd == 0.005  # custo propagado mesmo no erro


def test_retry_only_requested_fields_still_returns_full_object(monkeypatch):
    """No retry o prompt inclui o erro; a resposta ainda traz TODOS os campos."""
    prov = _install(monkeypatch, _FakeProvider(_good_payload()))
    req = _req(campos_com_erro=[
        CampoComErro(nome="resumo", erro="estourou limite", valor_anterior="x" * 200),
    ])
    out = asyncio.run(write_ficha_fields(req))
    assert out.success is True
    assert set(out.campos.keys()) == {"resumo", "pontos", "par"}
    # o prompt enviado carregou o bloco de correcao
    assert "CORRECAO OBRIGATORIA" in prov.last_kwargs["prompt"]


# ── Rota (mount isolado, provider mockado) ─────────────────────────────────


@pytest.fixture()
def client(monkeypatch):
    _install(monkeypatch, _FakeProvider(_good_payload(), cost=0.02))
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_route_happy_path(client):
    body = {
        "dossie": {"razao_social": "ACME LTDA"},
        "campos": [{"nome": "resumo", "tipo": "string", "limite_chars": 120,
                    "guidance": "1 frase", "exemplos": []},
                   {"nome": "pontos", "tipo": "array_string", "limite_chars": 80,
                    "quantidade": 2, "guidance": "bullets", "exemplos": []},
                   {"nome": "par", "tipo": "objeto_p1_p2", "limite_chars": 200,
                    "guidance": "dois p", "exemplos": []}],
    }
    r = client.post("/ficha/write-fields", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["success"] is True
    assert set(data["campos"].keys()) == {"resumo", "pontos", "par"}
    assert data["cost_usd"] == 0.02
    assert data["error"] is None


def test_route_validation_error_is_soft_200(monkeypatch):
    _install(monkeypatch, _FakeProvider(json.dumps({"resumo": "ok"})))  # faltam campos
    app = FastAPI()
    app.include_router(router)
    c = TestClient(app)
    body = {
        "dossie": {},
        "campos": [{"nome": "resumo", "tipo": "string", "limite_chars": 120},
                   {"nome": "pontos", "tipo": "array_string", "limite_chars": 80,
                    "quantidade": 2}],
    }
    r = c.post("/ficha/write-fields", json=body)
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is False
    assert data["campos"] == {}
    assert data["error"]

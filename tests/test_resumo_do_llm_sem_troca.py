"""O resumo_ato do LLM chega ao card como veio, no L1 completo e na triagem.

A troca do resumo "degenerado" pelo texto do evento disparou 0 vezes em 65.185 resumos de
30 dias, e saiu (protecao que so age no caso raro sai). O unico tratamento do resumo que
fica e o teto de 500 chars do materializer do garantis-shared. Se o LLM voltar a degenerar,
o card mostra o texto que o LLM escreveu.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import src.agents.mov_factsheet.agent as l1
import src.agents.mov_triage.agent as triagem

# Uma das assinaturas que a troca procurava: o LLM vaza o proprio meta-erro de JSON.
DEGENERADO = "The JSON was not valid. Here is the schema again."
MOV = {"mov_id": "m-1", "data": "2024-01-01", "texto": "Juntada de peticao da executada. " * 4}


def _resposta(card: dict) -> SimpleNamespace:
    return SimpleNamespace(
        text=json.dumps(card), input_tokens=1, output_tokens=1, cached_tokens=0,
        metadata={"model_variant": "text"},
    )


def test_l1_completo_mantem_o_resumo_do_llm(monkeypatch):
    async def _chamada(provider, **kw):
        return _resposta({"tipo_doc": "despacho", "relevancia_merito": "baixa",
                          "resumo_ato": DEGENERADO})

    monkeypatch.setattr(l1, "call_l1_with_vision_fallback", _chamada)
    monkeypatch.setattr(l1, "create_provider", lambda p: object())
    monkeypatch.setenv("L1_NEUTRAL_ENABLED", "true")

    out = asyncio.run(l1.classify_mov_factsheet(processo={"cnj": "0"}, mov=MOV))
    assert "error" not in out["card"]
    assert out["card"]["resumo_ato"] == DEGENERADO


def test_triagem_mantem_o_resumo_do_llm(monkeypatch):
    class _Provider:
        async def agenerate(self, **kw):
            return _resposta({"resumo_ato": DEGENERADO, "tipo_doc": "peticao",
                              "mov_merito": False, "mov_garantia_exec": False})

    monkeypatch.setattr(triagem, "create_provider", lambda p: _Provider())

    out = asyncio.run(triagem.classify_mov_triage(processo={"cnj": "0"}, mov=MOV))
    assert "error" not in out["card"]
    assert out["card"]["resumo_ato"] == DEGENERADO

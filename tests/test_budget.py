"""Onda 8 — budget e circuit breaker (§8.6): tetos em CODIGO.

Mutation-kills do §9.1: *"dublê que chama ferramenta em loop → para em 40"* e
*"3 falhas na mesma tool/doc → ferramenta some do menu"*. A factualidade cai
~42% de 2→150 tool calls; o teto baixo é a defesa, e estouro NUNCA vira número.
"""

import asyncio
from types import SimpleNamespace

import src.agents.calculo_ficha.investigador as inv_mod
from src.agents.calculo_ficha.ferramentas import (
    FALHAS_PARA_ABRIR,
    Budget,
    CircuitBreaker,
)
from src.agents.calculo_ficha.investigador import investigar
from src.agents.calculo_ficha.schemas import MontarGrafoRequest

from tests.test_calculo_ficha_investigador import _doc, _leitor_ok


class _ProviderTeimoso:
    """SEMPRE pede a mesma ferramenta — o agente que não sabe parar."""

    def __init__(self):
        self.chamadas = 0

    async def agenerate(self, **kwargs):
        self.chamadas += 1
        return SimpleNamespace(
            text='{"tool": "perguntar_ao_documento", "args": '
                 '{"doc_id": "carf:decisao.pdf", "pergunta": "?"}}',
            model="m", metadata={"cost_usd": 0.0},
        )


def _request() -> MontarGrafoRequest:
    return MontarGrafoRequest(
        dossie={}, documentos_indexados={"carf:decisao.pdf": _doc().to_dict()},
    )


def test_para_em_40_tool_calls_e_devolve_budget(monkeypatch):
    prov = _ProviderTeimoso()
    monkeypatch.setattr(inv_mod, "create_provider", lambda *_a, **_k: prov)
    r = asyncio.run(investigar(_request(), leitor_perguntar=_leitor_ok,
                               leitor_resumir=_leitor_ok))
    assert r.success is False
    assert "budget" in (r.error or "")
    # 40 turnos de decisao = 40 tool calls; a iteracao 41 detecta o estouro
    # ANTES de chamar o modelo de novo — nenhum turno alem do teto
    assert prov.chamadas == 40


def test_3_falhas_na_mesma_tool_doc_abrem_o_circuito(monkeypatch):
    invocacoes = {"n": 0}

    async def leitor_que_explode(doc_id, documento, **kw):
        invocacoes["n"] += 1
        raise RuntimeError("timeout do leitor")

    prov = _ProviderTeimoso()
    monkeypatch.setattr(inv_mod, "create_provider", lambda *_a, **_k: prov)
    r = asyncio.run(investigar(_request(), leitor_perguntar=leitor_que_explode,
                               leitor_resumir=leitor_que_explode))
    assert r.success is False and "budget" in (r.error or "")
    # ⚑ o Leitor só foi invocado 3 vezes — da 4a em diante o circuito estava
    # ABERTO e a chamada morreu no menu, sem tocar a ferramenta
    assert invocacoes["n"] == FALHAS_PARA_ABRIR


def test_breaker_unit():
    b = CircuitBreaker()
    assert b.disponivel("perguntar_ao_documento", "d1")
    for _ in range(FALHAS_PARA_ABRIR - 1):
        assert b.registrar_falha("perguntar_ao_documento", "d1") is False
    assert b.registrar_falha("perguntar_ao_documento", "d1") is True
    assert not b.disponivel("perguntar_ao_documento", "d1")
    # outro doc segue disponivel — o circuito e por (tool, doc)
    assert b.disponivel("perguntar_ao_documento", "d2")


def test_sucesso_zera_a_contagem():
    b = CircuitBreaker()
    b.registrar_falha("pedir_pagina", "d1")
    b.registrar_falha("pedir_pagina", "d1")
    b.registrar_sucesso("pedir_pagina", "d1")
    assert b.registrar_falha("pedir_pagina", "d1") is False   # recomecou do zero


def test_budget_estourado_por_custo():
    bud = Budget(custo_usd=2.5)
    assert "US$" in (bud.estourado() or "")

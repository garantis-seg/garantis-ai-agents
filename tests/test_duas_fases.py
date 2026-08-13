"""Onda 8 — as DUAS FASES (§6.1): decisão SEM schema, formatação COM.

Mutation-kill do §9.1: *"setar `response_schema` no turno de decisão → falha"*.
A supressão de tool-calling sob structured output é medida (arXiv:2606.25605);
o turno que decide ferramenta NUNCA leva `response_mime_type`/`response_schema`.
"""

import asyncio
import json
from types import SimpleNamespace

import src.agents.calculo_ficha.investigador as inv_mod
from src.agents.calculo_ficha.investigador import investigar
from src.agents.calculo_ficha.schemas import MontarGrafoRequest

from tests.test_calculo_ficha_investigador import (
    _ProviderRoteiro,
    _doc,
    _grafo_final,
    _leitor_ok,
)


def _request() -> MontarGrafoRequest:
    return MontarGrafoRequest(
        dossie={}, documentos_indexados={"carf:decisao.pdf": _doc().to_dict()},
    )


def test_decisao_sem_schema_formatacao_com_mime(monkeypatch):
    prov = _ProviderRoteiro([
        '{"tool": "perguntar_ao_documento", "args": {"doc_id": "carf:decisao.pdf", "pergunta": "?"}}',
        '{"fim": true}',
        _grafo_final(),
    ])
    monkeypatch.setattr(inv_mod, "create_provider", lambda *_a, **_k: prov)
    r = asyncio.run(investigar(_request(), leitor_perguntar=_leitor_ok,
                               leitor_resumir=_leitor_ok))
    assert r.success

    decisao_1, decisao_2, formatacao = prov.chamadas
    # ⚑ turnos de DECISAO: schema-free, sempre
    for turno in (decisao_1, decisao_2):
        assert "response_mime_type" not in turno
        assert "response_schema" not in turno
        assert turno["temperature"] == 0.0
    # ⚑ turno de FORMATACAO: JSON constrained
    assert formatacao["response_mime_type"] == "application/json"


def test_texto_livre_no_turno_de_decisao_e_tolerado_com_retry(monkeypatch):
    """O parser tolerante aceita JSON no meio de prosa; prosa SEM JSON conta
    como falha de protocolo e nao vira chamada fantasma."""
    prov = _ProviderRoteiro([
        'Vou investigar o principal. {"tool": "perguntar_ao_documento", '
        '"args": {"doc_id": "carf:decisao.pdf", "pergunta": "principal?"}} obrigado.',
        "hmm deixa eu pensar…",     # sem JSON → falha de protocolo, re-turno
        '{"fim": true}',
        _grafo_final(),
    ])
    monkeypatch.setattr(inv_mod, "create_provider", lambda *_a, **_k: prov)
    r = asyncio.run(investigar(_request(), leitor_perguntar=_leitor_ok,
                               leitor_resumir=_leitor_ok))
    assert r.success
    assert len(prov.chamadas) == 4
    assert "sem chamada JSON valida" in prov.chamadas[2]["prompt"]


def test_formatacao_invalida_reemite_com_erros(monkeypatch):
    ruim = json.dumps({"celulas": [
        {"id": "outra", "tipo": "dado", "valor": 1.0, "origem": "factual"},
    ]})  # sem a celula de resultado — estrutura invalida
    prov = _ProviderRoteiro(['{"fim": true}', ruim, _grafo_final()])
    monkeypatch.setattr(inv_mod, "create_provider", lambda *_a, **_k: prov)
    r = asyncio.run(investigar(_request(), leitor_perguntar=_leitor_ok,
                               leitor_resumir=_leitor_ok))
    assert r.success
    assert "ERROS da sua tentativa anterior" in prov.chamadas[2]["prompt"]

# -*- coding: utf-8 -*-
"""ciclo_garantia montado em código (2026-06-19) — não pelo LLM.

O L3 loopava re-listando os eventos (680046: ~880 eventos / 145KB malformado →
indeterminado, não-determinístico). Removido do response_schema; montado
deterministicamente dos lifecycle_garantia do input. Determinístico = bounded.
"""
from src.agents.merito_synthesis.agent import _assemble_ciclo_garantia

_KEYS = {"data", "processo_numero", "evento", "tipo_garantia", "status_pos", "motivo_recusa"}


def test_merge_sort_shape():
    ps = [
        {"processo_numero": "A", "lifecycle_garantia": [
            {"data": "2024-03-01", "evento": "apresentacao", "tipo_garantia": "seguro_garantia", "status_pos": "apresentado"},
            {"data": "2024-01-01", "evento": "aceitacao", "tipo_garantia": "seguro_garantia", "status_pos": "aceito"},
        ]},
        {"processo_numero": "B", "lifecycle_garantia": [
            {"data": "2024-02-01", "evento": "levantamento", "tipo_garantia": "seguro_garantia", "status_pos": "levantado"},
        ]},
    ]
    out = _assemble_ciclo_garantia(ps)
    assert [e["data"] for e in out] == ["2024-01-01", "2024-02-01", "2024-03-01"]  # sorted ASC
    assert out[0]["processo_numero"] == "A" and out[0]["evento"] == "aceitacao"
    assert out[1]["processo_numero"] == "B"
    assert all(set(e.keys()) == _KEYS for e in out)  # shape = CicloGarantiaEvent


def test_dedupe_exato():
    ps = [{"processo_numero": "A", "lifecycle_garantia": [
        {"data": "2024-01-01", "evento": "aceitacao", "status_pos": "aceito"},
        {"data": "2024-01-01", "evento": "aceitacao", "status_pos": "aceito"},  # dup
    ]}]
    assert len(_assemble_ciclo_garantia(ps)) == 1


def test_vazio_e_none():
    assert _assemble_ciclo_garantia([]) == []
    assert _assemble_ciclo_garantia(None) == []
    assert _assemble_ciclo_garantia([{"processo_numero": "A", "lifecycle_garantia": None}]) == []


def test_bounded_nunca_passa_do_input():
    # 200 eventos reais -> NUNCA mais que 200 (sem loop). O LLM gerava 880 de ~120.
    ps = [{"processo_numero": "A", "lifecycle_garantia": [
        {"data": f"2024-{i % 12 + 1:02d}-{i % 28 + 1:02d}", "evento": "apresentacao", "status_pos": "apresentado"}
        for i in range(200)
    ]}]
    out = _assemble_ciclo_garantia(ps)
    assert len(out) <= 200


def test_aceita_objeto_pydantic():
    # robusto a ProcessoSynthesisMin (atributo) além de dict
    from src.agents.merito_synthesis.schemas import ProcessoSynthesisMin
    ps = [ProcessoSynthesisMin(processo_numero="X", lifecycle_garantia=[
        {"data": "2024-05-01", "evento": "acionamento", "status_pos": "nenhum"}])]
    out = _assemble_ciclo_garantia(ps)
    assert len(out) == 1 and out[0]["processo_numero"] == "X"

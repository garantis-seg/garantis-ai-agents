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


def test_decoupling_llm_schema_vs_response():
    # O LLM usa MeritoSynthesisCard (base, SEM ciclo → não loopa); a resposta usa
    # MeritoSynthesisCardOut (COM ciclo). O response_model NÃO pode estripar o ciclo
    # montado em código (era o bug do 680046: _assemble dava 26 mas a resposta vinha 0).
    from src.agents.merito_synthesis.schemas import (
        MeritoSynthesisCard, MeritoSynthesisCardOut, MeritoSynthesisResponse)
    assert "ciclo_garantia" not in MeritoSynthesisCard.model_json_schema()["properties"]
    assert "ciclo_garantia" in MeritoSynthesisCardOut.model_json_schema()["properties"]
    card = {"merito_id": 1, "merito_context": "global", "risco": "Alto",
            "ciclo_garantia": [{"data": "2024-01-01", "processo_numero": "A",
                                "evento": "aceitacao", "status_pos": "aceito"}]}
    resp = MeritoSynthesisResponse(card=card)
    assert len(resp.model_dump()["card"]["ciclo_garantia"]) == 1  # NÃO estripado


def test_ciclo_aceita_valores_reais_amplos():
    # ciclo_garantia é list[dict] (não list[CicloGarantiaEvent]) — os valores vêm do
    # lifecycle real (evento 'acionamento'/'nenhum', 'reforco' sem cedilha), que os
    # Literals estritos rejeitariam → 500. Permissivo NÃO pode levantar.
    from src.agents.merito_synthesis.schemas import MeritoSynthesisCardOut, MeritoSynthesisResponse
    card = {"merito_id": 1, "merito_context": "global", "risco": "Alto", "ciclo_garantia": [
        {"data": "2024-01-01", "processo_numero": "A", "evento": "acionamento", "status_pos": "nenhum"},
        {"data": "2024-02-01", "processo_numero": "B", "evento": "reforco", "status_pos": "aceito"}]}
    resp = MeritoSynthesisResponse(card=MeritoSynthesisCardOut(**card))
    assert len(resp.model_dump()["card"]["ciclo_garantia"]) == 2

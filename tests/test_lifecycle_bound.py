# -*- coding: utf-8 -*-
"""Bound do lifecycle_garantia no prompt do L3 (2026-06-19).

Processo gigante (1940 movs → ~280 eventos de lifecycle) despejava ~22KB no prompt
→ L3 degenerava (145KB ciclo_garantia → JSON malformado → indeterminado). head+tail.
"""
from src.agents.merito_synthesis.prompts import (
    _LIFECYCLE_HEAD,
    _LIFECYCLE_MAX,
    _LIFECYCLE_TAIL,
    _summarize_processo_synthesis,
)
from src.agents.merito_synthesis.schemas import ProcessoSynthesisMin


def _ps(n_events):
    lc = [
        {"data": f"2024-{(i % 12) + 1:02d}-01", "evento": f"ev{i}",
         "tipo_garantia": "seguro_garantia", "status_pos": "aceita"}
        for i in range(n_events)
    ]
    return ProcessoSynthesisMin(processo_numero="0011683-43.2008.8.26.0008",
                                lifecycle_garantia=lc)


def test_lifecycle_grande_head_tail():
    out = _summarize_processo_synthesis(_ps(280))
    assert "Lifecycle garantia (280 eventos)" in out          # header mostra total REAL
    assert "omitidos" in out                                  # marcador presente
    assert "ev0" in out and "ev1 " in out                     # head (origem) preservado
    assert "ev279" in out and "ev278" in out                  # tail (estado atual) preservado
    assert "ev140" not in out                                 # miolo omitido
    # nº de linhas de evento renderizadas == head+tail (não 280)
    ev_lines = [l for l in out.splitlines() if "-> aceita" in l]
    assert len(ev_lines) == _LIFECYCLE_MAX


def test_lifecycle_pequeno_intacto():
    out = _summarize_processo_synthesis(_ps(5))
    assert "Lifecycle garantia (5 eventos)" in out
    assert "omitidos" not in out
    ev_lines = [l for l in out.splitlines() if "-> aceita" in l]
    assert len(ev_lines) == 5                                 # todos renderizados


def test_lifecycle_no_limite_intacto():
    out = _summarize_processo_synthesis(_ps(_LIFECYCLE_MAX))   # exatamente no teto
    assert "omitidos" not in out
    ev_lines = [l for l in out.splitlines() if "-> aceita" in l]
    assert len(ev_lines) == _LIFECYCLE_MAX

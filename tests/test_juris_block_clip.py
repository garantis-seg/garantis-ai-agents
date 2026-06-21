"""Ajuste 2026-06-21: ementa do provider jurisprudencias.ai injetada no L2 NAO
pode mais ser truncada so no head — o DISPOSITIVO (provido/improvido = quem
ganhou) vem no FIM da ementa. _clip_head_tail preserva materia (head) + dispositivo
(tail). Bug anterior: cap 300 no head jogava o resultado fora.
"""
from __future__ import annotations

from src.agents.processo_synthesis.prompts import _clip_head_tail


def test_short_ementa_passes_intact():
    short = "DIREITO TRIBUTARIO. PIS/COFINS. EXCLUSAO DO ICMS. Recurso provido."
    assert _clip_head_tail(short, head=700, tail=400) == short


def test_long_ementa_preserves_dispositivo_at_tail():
    body = "X" * 2000
    ementa = "EMENTA: DIREITO TRIBUTARIO. ICMS BASE PIS COFINS. " + body + " RECURSO DA FAZENDA NAO PROVIDO."
    clipped = _clip_head_tail(ementa, head=700, tail=400)
    assert "DIREITO TRIBUTARIO" in clipped        # materia (head) sobrevive
    assert "NAO PROVIDO" in clipped               # DISPOSITIVO (tail) sobrevive — o fix
    assert "[…]" in clipped                       # miolo elidido
    assert len(clipped) < len(ementa)


def test_none_safe():
    assert _clip_head_tail(None, head=700, tail=400) == ""

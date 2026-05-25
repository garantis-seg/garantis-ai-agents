"""Bloco DECISOES PARADIGMA carregado de ref.tese_decisao_individual.

Pre-filtrados por tese_canonica_id (tipo-consistent), entao mesmo bloco
serve todas as variants fiscal/trab/civel/misto. Quando paradigmas==[]
(tese sem paradigmas curados), bloco eh suprimido no join."""
from __future__ import annotations

from src.agents.merito_synthesis.prompts import build_merito_synthesis_prompt
from src.agents.merito_synthesis.schemas import (
    MeritoSynthesisRequest,
    ParadigmaMin,
)


def test_paradigmas_block_absent_when_empty():
    """Default paradigmas=[] -> bloco nao aparece, sem trailing blank line extra."""
    req = MeritoSynthesisRequest(merito_id=1)
    p = build_merito_synthesis_prompt(req)
    assert "DECISOES PARADIGMA" not in p
    # Garante que filtro de empties no join nao deixou separador duplicado
    assert "\n\n\n" not in p


def test_paradigmas_block_renders_with_data():
    """paradigmas populated -> bloco com header + 1 linha por paradigma."""
    req = MeritoSynthesisRequest(
        merito_id=1,
        paradigmas=[
            ParadigmaMin(
                tribunal="STJ", instancia="repetitivo",
                data_decisao="2024-03-15",
                sentido="pro_fazenda",
                ementa_resumo="Acordao firmando ICMS-ST devido na origem.",
                relator="Min. Mauro Campbell",
            ),
            ParadigmaMin(
                tribunal="TJSP", instancia="2g",
                data_decisao="2024-06-20",
                sentido="pro_contribuinte",
                ementa_resumo="Sentenca 1g revertida em apelacao.",
            ),
        ],
    )
    p = build_merito_synthesis_prompt(req)
    assert "=== DECISOES PARADIGMA DESTA TESE ===" in p
    # Paradigma 1: STJ
    assert "STJ" in p
    assert "repetitivo" in p
    assert "2024-03-15" in p
    assert "pro_fazenda" in p
    assert "ICMS-ST" in p
    assert "Rel. Min. Mauro Campbell" in p
    # Paradigma 2: TJSP (sem relator — campo opcional)
    assert "TJSP" in p
    assert "2024-06-20" in p
    assert "pro_contribuinte" in p


def test_paradigmas_block_placed_after_jurisprudencia_before_snapshot():
    """Ordenamento: JURISPRUDENCIA < DECISOES PARADIGMA < SNAPSHOT ANTERIOR."""
    req = MeritoSynthesisRequest(
        merito_id=1,
        paradigmas=[ParadigmaMin(tribunal="STJ", sentido="pro_fazenda")],
    )
    p = build_merito_synthesis_prompt(req)
    pos_jur = p.find("=== JURISPRUDENCIA")
    pos_para = p.find("=== DECISOES PARADIGMA")
    pos_snap = p.find("=== SNAPSHOT ANTERIOR")
    assert pos_jur < pos_para < pos_snap, (
        f"Ordem esperada: JURISPRUDENCIA < DECISOES PARADIGMA < SNAPSHOT. "
        f"Got jur={pos_jur} paradigma={pos_para} snapshot={pos_snap}"
    )


def test_paradigmas_block_handles_missing_optional_fields():
    """Render tolera campos opcionais ausentes (tribunal-only ParadigmaMin)."""
    req = MeritoSynthesisRequest(
        merito_id=1,
        paradigmas=[ParadigmaMin(tribunal="TRF3")],
    )
    p = build_merito_synthesis_prompt(req)
    assert "=== DECISOES PARADIGMA DESTA TESE ===" in p
    assert "TRF3" in p
    assert "(sem ementa)" in p  # placeholder quando ementa_resumo None

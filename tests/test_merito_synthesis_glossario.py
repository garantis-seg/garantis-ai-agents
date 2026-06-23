"""#2 (2026-06-23): o GLOSSARIO ROLES + REGRA DURA 3-step "grosseira" foram
substituidos pelo Tomador injetado como FATO (razao_social/CNPJ) + 1 linha
anti-inversao. Validado no harness (234 r3): exact/within1 = v2.7, false_baixo
-1,3% (miss-perigoso melhor, estavel em 2 runs), recall +. _build_glossary_roles
manteve o NOME (compat do call site) mas agora recebe req e emite o bloco-fato.
"""
from __future__ import annotations

from src.agents.merito_synthesis.prompts import build_merito_synthesis_prompt
from src.agents.merito_synthesis.schemas import MeritoSynthesisRequest


def _req(razao="ACME LTDA", cnpj="12345678000190") -> MeritoSynthesisRequest:
    return MeritoSynthesisRequest(
        merito_id=1, merito_context="monit_poletto",
        razao_social=razao, cnpj_principal=cnpj,
    )


def test_tomador_fato_present_before_merito():
    p = build_merito_synthesis_prompt(_req())
    assert "O TOMADOR (FATO" in p
    assert p.find("O TOMADOR (FATO") < p.find("=== MERITO")


def test_tomador_identity_injected_as_fact():
    p = build_merito_synthesis_prompt(_req(razao="BANCO MERCANTIL SA", cnpj="11222333000144"))
    assert "BANCO MERCANTIL SA" in p
    assert "11222333000144" in p


def test_tomador_fact_fallbacks():
    assert "99888777000166" in build_merito_synthesis_prompt(_req(razao=None, cnpj="99888777000166"))
    assert "titular do merito" in build_merito_synthesis_prompt(_req(razao=None, cnpj=None))


def test_anti_inversion_rule_present():
    """A unica regra de polo que sobra: o `sentido` JA vem do ponto de vista do
    Tomador — nao reinverter (cobre o caso m=3 Banco Mercantil)."""
    p = build_merito_synthesis_prompt(_req())
    assert "sentido" in p
    assert "NAO reinverta" in p
    assert "Tomador ganhou" in p


def test_old_glossario_and_regra_dura_removed():
    p = build_merito_synthesis_prompt(_req())
    assert "GLOSSARIO ROLES" not in p
    assert "(a) == (b)" not in p  # a REGRA DURA 3-step grosseira

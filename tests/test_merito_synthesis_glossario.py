"""Bug 5a handoff: glossario fixo no L3 prompt p/ eliminar oscilacao
Tomador/Segurado/Garantido entre cascades.

Sem glossario, Gemini flickava em todo proc com "procedente" SEM contexto
explicito de polo — atribuiu "ALTO" e "MEDIO" alternadamente no MESMO merito
ate redigia frases contraditorias dentro da mesma justificativa (cf. m=3
snapshot 304: "sentenca favoravel ao Banco Mercantil" + "alta chance de
perda para parte garantida [Uniao]" — Banco Mercantil e o Tomador, nao a
Uniao).

Acceptance: glossario presente no prompt, com REGRA DURA explicita
mapeando "Tomador ganhou -> BAIXO" e "Tomador perdeu -> ALTO".
"""
from __future__ import annotations

from src.agents.merito_synthesis.prompts import build_merito_synthesis_prompt
from src.agents.merito_synthesis.schemas import MeritoSynthesisRequest


def _empty_request() -> MeritoSynthesisRequest:
    """Request minimo (sem syntheses) p/ inspecionar estrutura do prompt."""
    return MeritoSynthesisRequest(merito_id=1, merito_context="monit_poletto")


def test_glossario_present_in_prompt():
    """Bloco GLOSSARIO renderiza no prompt."""
    p = build_merito_synthesis_prompt(_empty_request())
    assert "=== GLOSSARIO ROLES EM SEGURO GARANTIA JUDICIAL" in p


def test_glossario_before_merito_block():
    """Glossario aparece ANTES do bloco MERITO (prioridade no contexto)."""
    p = build_merito_synthesis_prompt(_empty_request())
    pos_gloss = p.find("=== GLOSSARIO")
    pos_merito = p.find("=== MERITO")
    assert pos_gloss < pos_merito, "Glossario deveria preceder MERITO no prompt"


def test_glossario_defines_tomador_segurado_polarity():
    """Mapeamento canonico: contribuinte = Tomador; Fazenda = Segurado/Garantido."""
    p = build_merito_synthesis_prompt(_empty_request())
    # Tomador = contribuinte/devedor (em exec fiscal)
    assert "Tomador" in p
    assert "contribuinte" in p
    # Segurado/Garantido = Fazenda
    assert "Segurado" in p and "Garantido" in p
    assert "Fazenda" in p


def test_glossario_maps_procedente_to_risco_polarity():
    """Bullet canonico: 'procedente p/ contribuinte = BAIXO' + 'improcedente = ALTO'."""
    p = build_merito_synthesis_prompt(_empty_request())
    # Caso BAIXO: Tomador ganhou
    assert "FAVORAVEL ao Tomador" in p
    assert "BAIXO" in p
    # Caso ALTO: Tomador perdeu
    assert "DESFAVORAVEL ao Tomador" in p
    assert "ALTO" in p


def test_glossario_blocks_synonimo_tomador_garantido():
    """REGRA DURA: NUNCA usar 'Garantido' e 'Tomador' como sinonimos."""
    p = build_merito_synthesis_prompt(_empty_request())
    assert "NUNCA usar" in p
    assert "Garantido" in p
    assert "Tomador" in p


def test_glossario_blocks_polarity_inversion_narrative():
    """REGRA DURA: NUNCA inverter favoravel/desfavoravel na narrativa.
    Cobre o caso m=3 onde Gemini escreveu 'sentenca favoravel ao Banco Mercantil'
    quando Banco Mercantil e o Tomador e a sentenca foi DESFAVORAVEL."""
    p = build_merito_synthesis_prompt(_empty_request())
    assert "NUNCA inverter" in p
    assert "favoravel/desfavoravel" in p


def test_glossario_recurso_nao_neutraliza_alto():
    """Recurso pendente NAO baixa risco — ALTO ate transito FAVORAVEL Tomador."""
    p = build_merito_synthesis_prompt(_empty_request())
    assert "Recurso pendente NAO neutraliza" in p
    assert "ALTO permanece ate transito FAVORAVEL ao Tomador" in p


def test_glossario_regra_dura_three_step_check():
    """Checklist 3-step explicito: (a) quem e Tomador, (b) quem ganhou, (c) compare."""
    p = build_merito_synthesis_prompt(_empty_request())
    assert "REGRA DURA" in p
    assert "(a) quem e o Tomador" in p
    assert "(b) quem ganhou" in p
    assert "(a) == (b)" in p
    assert "(a) != (b)" in p


def test_glossario_examples_for_both_polarities():
    """Cobre cenarios canonicos do Bug 5a handoff:
    'procedente para Tomador = BAIXO' e 'procedente para Fazenda = ALTO'.

    Sao representados via:
      (a) bullet FAVORAVEL ao Tomador -> BAIXO
      (b) bullet DESFAVORAVEL ao Tomador -> ALTO
    """
    p = build_merito_synthesis_prompt(_empty_request())
    # Caso BAIXO: procedente p/ contribuinte (=Tomador)
    assert "procedente p/ contribuinte" in p
    assert "Tomador ganhou" in p
    # Caso ALTO: improcedente p/ contribuinte (= Fazenda ganhou)
    assert "improcedente p/ contribuinte" in p
    assert "Tomador perdeu" in p

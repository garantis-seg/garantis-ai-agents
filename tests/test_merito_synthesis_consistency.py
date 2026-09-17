"""Bug 5c handoff: CONSISTENCY CHECK explicito no L3 prompt p/ eliminar
contradicao 'argumento Alto + risco Medio'.

Cascade d86c228e m=3 (snap 319) produziu:
  contribuicao_no_risco: "empurra o risco para Alto"
  justificativa:        "elevando o risco de acionamento"
  risco final:          "Medio"  <- contradicao

Acceptance: bloco CONSISTENCY CHECK obrigatorio renderiza no prompt
ANTES dos inputs, com regras explicitas:
  - pro-Alto -> risco final Alto/Altissimo (NUNCA Medio/Baixo)
  - pro-Baixo -> risco final Baixo (NUNCA Medio/Alto)
  - Medio so legitimo com contrapesos explicitos na narrativa

NAO testa o output do LLM (Gemini residual flicker; ataque ortogonal).
"""
from __future__ import annotations

from src.agents.merito_synthesis.prompts import (
    _build_consistency_check,
    build_merito_synthesis_prompt,
)
from src.agents.merito_synthesis.schemas import MeritoSynthesisRequest


def _empty_request() -> MeritoSynthesisRequest:
    return MeritoSynthesisRequest(merito_id=1, merito_context="monit_poletto")


# ── Presence + ordering ────────────────────────────────────────────────────


def test_consistency_check_present_in_prompt():
    p = build_merito_synthesis_prompt(_empty_request())
    assert "=== CONSISTENCY CHECK" in p


def test_consistency_check_after_glossario_before_merito():
    """CONSISTENCY CHECK fica DEPOIS do GLOSSARIO (regras roles primeiro) e
    ANTES do bloco MERITO (inputs)."""
    p = build_merito_synthesis_prompt(_empty_request())
    pos_gloss = p.find("=== GLOSSARIO")
    pos_check = p.find("=== CONSISTENCY CHECK")
    pos_merito = p.find("=== MERITO")
    assert pos_gloss < pos_check < pos_merito, (
        f"Ordem esperada: GLOSSARIO < CONSISTENCY CHECK < MERITO. "
        f"Got gloss={pos_gloss} check={pos_check} merito={pos_merito}"
    )


# ── Regras pro-Alto ────────────────────────────────────────────────────────


def test_consistency_check_lists_pro_alto_phrases():
    """Lista de frases que TRIGGER risco Alto obrigatorio.

    ⛔ "probabilidade remota de exito" SAIU da lista de proposito (c4452ea, v2.7,
    2026-06-20): prob_exito virou CONTEXTO, quem decide o nivel e a Matriz de Risco
    (Regra F). Ela voltar como gatilho pro-Alto reintroduz o over-rating que o A/B
    do l3_poletto mediu — por isso o assert NEGATIVO, sobre o bloco do check."""
    p = build_merito_synthesis_prompt(_empty_request())
    pro_alto_phrases = [
        "empurra o risco para Alto",
        "alta chance de reversao desfavoravel ao Tomador",
        "elevando o risco de acionamento da apolice",
        "jurisprudencia desfavoravel a tese",
        "tendencia de perda em instancias superiores",
    ]
    for phrase in pro_alto_phrases:
        assert phrase in p, f"Frase pro-Alto faltando no CONSISTENCY CHECK: {phrase!r}"
    assert "remota" not in _build_consistency_check(), (
        "prob_exito 'remota' voltou a ser gatilho pro-Alto no CONSISTENCY CHECK — "
        "desde v2.7 ela e contexto (Regra F), nao decide o nivel"
    )


def test_consistency_check_pro_alto_blocks_medio_baixo():
    """Quando argumentos pro-Alto: risco final DEVE ser Alto/Altissimo,
    NUNCA Medio nem Baixo."""
    p = build_merito_synthesis_prompt(_empty_request())
    # Esse e o coracao da regra
    assert "DEVE ser \"Alto\" OU \"Altissimo\"" in p
    assert "NUNCA Medio ou Baixo" in p


# ── Regras pro-Baixo (simetrico) ───────────────────────────────────────────


def test_consistency_check_reverso_pro_baixo():
    """Simetria: pro-Baixo (Tomador ganhou + transito + tese pro_contribuinte)
    -> risco NAO pode ser Medio nem Alto."""
    p = build_merito_synthesis_prompt(_empty_request())
    assert "Reverso simetrico" in p
    # v2.7.1: a string "transito FAVORAVEL" vinha do glossario (removido no #2);
    # o bloco consistency em si segue intacto — testa o conteudo dele.
    assert "FAVORAVEL" in p
    assert "Deve ser \"Baixo\"" in p


# ── Opcoes A/B (reescrever OU elevar risco) ────────────────────────────────


def test_consistency_check_two_options_for_medio_apesar_alto():
    """Quando LLM inclinado a Medio com argumentos pro-Alto: OPCAO A (reescrever
    narrativa com contrapesos) OU OPCAO B (elevar p/ Alto). NUNCA contradicao."""
    p = build_merito_synthesis_prompt(_empty_request())
    assert "OPCAO A:" in p
    assert "OPCAO B:" in p
    assert "reescreva justificativa" in p
    assert "eleve risco" in p


def test_consistency_check_contrapesos_examples():
    """OPCAO A da exemplos concretos de contrapesos que sustentam Medio."""
    p = build_merito_synthesis_prompt(_empty_request())
    # Pelo menos 2 dos exemplos canonicos
    contrapesos = [
        "garantia em renovacao",
        "tomador com historico solido",
        "prazo longo ate transito",
        "1g consolidada favoravel",
    ]
    found = sum(1 for c in contrapesos if c in p)
    assert found >= 2, f"Esperava 2+ exemplos de contrapesos; achou {found}"


def test_consistency_check_explica_medio_legitimo():
    """Medio NAO e proibido — e legitimo quando narrativa o sustenta."""
    p = build_merito_synthesis_prompt(_empty_request())
    assert "Medio e veredict LEGITIMO" in p or "Medio e veredict legitimo" in p.lower()
    assert "contrapesos explicitos" in p


def test_consistency_check_references_real_cascade():
    """Bloco cita o caso concreto que motivou a regra (cascade snapshot 319 m=3).
    Sustenta confianca no LLM de que a regra nao e arbitraria."""
    p = build_merito_synthesis_prompt(_empty_request())
    assert "snapshot 319" in p or "cascades anteriores" in p
    # Reproduz o padrao que falhou
    assert "contribuicao_no_risco diz" in p or "contradicoes" in p


def test_consistency_check_releitura_explicit():
    """Step 1: releia explicitamente os campos pro-risco que o LLM EMITE.

    Eram 4; `trajetoria_motivo` saiu de proposito (7e79a93, 2026-05-24): o
    materializer ignora o campo (schemas.py: "LLM NAO preenche esses campos"), e
    pedir a releitura dele gastava token num campo morto. O assert agora olha o
    PASSO 1 do check — nao o prompt inteiro, onde "justificativa" casa em qualquer
    lugar — e barra o campo morto de voltar."""
    p = build_merito_synthesis_prompt(_empty_request())
    check = _build_consistency_check()
    passo_1 = " ".join(check.split("\n\n2.")[0].split())
    assert "Releia" in passo_1
    for campo in ("contribuicao_no_risco", "justificativa", "narrativa_executiva"):
        assert f"`{campo}`" in passo_1 or f".{campo}`" in passo_1, (
            f"passo 1 do CONSISTENCY CHECK nao manda reler {campo!r}"
        )
    assert "trajetoria_motivo" not in p

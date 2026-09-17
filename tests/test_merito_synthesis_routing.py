"""Routing por tipo_judicial dominante + keyword presence per variant L3.

Cobre routing (8 cenarios incluindo threshold 80% edge case), prompt_version
format, cross-contamination guards entre variants fiscal/trab/civel/misto."""
from __future__ import annotations

import pytest

from src.agents.merito_synthesis.prompts import (
    PROMPT_VERSION_BASE,
    _build_rules,
    _determine_tipo_dominante,
    _prompt_version_for,
    build_merito_synthesis_prompt,
)
from src.agents.merito_synthesis.schemas import (
    MeritoSynthesisRequest,
    ProcessoSynthesisMin,
)


def _ps(tipo: str | None, n: str = "0000000-00.0000.0.00.0000") -> ProcessoSynthesisMin:
    """Factory minimo de ProcessoSynthesisMin com tipo_judicial setado."""
    return ProcessoSynthesisMin(processo_numero=n, tipo_judicial=tipo)  # type: ignore[arg-type]


# ── Routing: dominancia clara ──────────────────────────────────────────────


def test_routing_fiscal_dominante():
    """4 fiscal + 1 civel = 80% fiscal -> dominante 'fiscal'."""
    procs = [_ps("fiscal")] * 4 + [_ps("civel")]
    assert _determine_tipo_dominante(procs) == "fiscal"


def test_routing_trabalhista_puro():
    """3 procs todos trabalhista -> 'trabalhista'."""
    procs = [_ps("trabalhista")] * 3
    assert _determine_tipo_dominante(procs) == "trabalhista"


def test_routing_civel_puro():
    """2 procs todos civel -> 'civel'."""
    procs = [_ps("civel")] * 2
    assert _determine_tipo_dominante(procs) == "civel"


# ── Routing: fallback pra 'misto' ──────────────────────────────────────────


def test_routing_empty_list():
    """Lista vazia -> 'misto' (sem sinal pra escolher dominante)."""
    assert _determine_tipo_dominante([]) == "misto"


def test_routing_all_null_tipo():
    """Todos os procs com tipo_judicial=None -> 'misto'."""
    procs = [_ps(None), _ps(None), _ps(None)]
    assert _determine_tipo_dominante(procs) == "misto"


def test_routing_50_50_tie():
    """2 fiscal + 2 civel = 50/50 -> 'misto' (nenhum atinge 80%)."""
    procs = [_ps("fiscal"), _ps("fiscal"), _ps("civel"), _ps("civel")]
    assert _determine_tipo_dominante(procs) == "misto"


def test_routing_75_25_below_threshold():
    """3 fiscal + 1 civel = 75% -> 'misto' (abaixo do threshold 80%)."""
    procs = [_ps("fiscal")] * 3 + [_ps("civel")]
    assert _determine_tipo_dominante(procs) == "misto"


def test_routing_80_20_at_threshold():
    """4 fiscal + 1 civel = exatamente 80% -> 'fiscal' (atinge threshold).

    Guard sobre operador `>=` na funcao routing — `>` quebraria o caso de borda."""
    procs = [_ps("fiscal")] * 4 + [_ps("civel")]
    assert _determine_tipo_dominante(procs) == "fiscal"


# ── Prompt version variant suffix ──────────────────────────────────────────


def test_prompt_version_format():
    """_prompt_version_for(tipo) concatena base + tipo dominante."""
    assert _prompt_version_for("fiscal") == "merito_synthesis.v2.9-fiscal"
    assert _prompt_version_for("trabalhista") == "merito_synthesis.v2.9-trabalhista"
    assert _prompt_version_for("civel") == "merito_synthesis.v2.9-civel"
    assert _prompt_version_for("misto") == "merito_synthesis.v2.9-misto"


def test_prompt_version_base_constant():
    """PROMPT_VERSION_BASE = v2.9 (remove residuo aiim do texto, 2026-07-14)."""
    assert PROMPT_VERSION_BASE == "merito_synthesis.v2.9"
    assert PROMPT_VERSION_BASE.startswith("merito_synthesis.")


# ── Rules block: keywords especificos por variant ──────────────────────────
#
# ⚠️ Os paradigmas de JURISPRUDENCIA (Tema 372 CSLL, Tema 1226, DIFAL, Tema 725
# Pejotizacao) sairam do L3 de proposito em a0a82f8 (v2.2, 2026-05-25): a juris
# passou a pesar SO no L2 (regras J/J.1/J.2), porque aplicada nas duas camadas
# contava 2x. Um assert "Tema 372 not in p" virou VACUO (a string nao existe em
# variant nenhuma) — os marcadores abaixo sao os EXCLUSIVOS vivos de cada variant,
# entao o guard de cross-contamination volta a ter os dois lados.


def test_rules_fiscal_keywords():
    """Variant fiscal contem vocabulario fiscal exclusivo (EF, pre-executividade,
    CTN art. 174, tese pro_fazenda_firmado) e NAO contem termos trab/civel-exclusivos."""
    p = _build_rules("fiscal")
    # Fiscal-specific
    assert "pro_fazenda_firmado" in p, "Fiscal deve usar a tese pro_fazenda_firmado na ESCALA"
    assert "CTN art. 174" in p, "Fiscal deve citar prescricao intercorrente (CTN art. 174)"
    assert "credito tributario" in p, "Fiscal deve falar em credito tributario"
    assert "Execucao Fiscal" in p
    assert "Anulatoria" in p, "Fiscal deve mencionar Anulatoria conexa (regra H)"
    assert "pre-executividade" in p, "Fiscal deve listar excecao de pre-executividade processual"
    # Trab/civel-exclusive devem estar AUSENTES (cross-contamination guard)
    assert "AIRR" not in p, "AIRR (trabalhista) nao deve aparecer em fiscal"
    assert "Sumula 331 TST" not in p, "Sumula 331 TST nao deve aparecer em fiscal"
    assert "deposito recursal" not in p, "deposito recursal (trabalhista) nao deve aparecer em fiscal"


def test_rules_trabalhista_keywords():
    """Variant trabalhista contem termos trabalhistas exclusivos (TST, AIRR,
    Sumula 331, TRT, deposito recursal) e NAO contem termos fiscal-exclusivos."""
    p = _build_rules("trabalhista")
    # Trabalhista-specific
    assert "TST" in p, "Trabalhista deve citar TST (Tribunal Superior do Trabalho)"
    assert "AIRR" in p, "Trabalhista deve listar AIRR como recurso processual"
    assert "Sumula 331" in p, "Trabalhista deve citar Sumula 331 TST (terceirizacao)"
    assert "TRT" in p, "Trabalhista deve citar acordao TRT (2g trabalhista)"
    assert "deposito recursal" in p, "Trabalhista deve mencionar deposito recursal (CLT art. 899)"
    assert "Cumprimento Provisorio" in p or "cumprimento provisorio" in p.lower(), (
        "Trabalhista deve mencionar Cumprimento Provisorio (suspensao analoga regra H)"
    )
    # Fiscal-exclusive devem estar AUSENTES (cross-contamination guard)
    assert "pro_fazenda_firmado" not in p, "tese pro_fazenda_firmado (fiscal) nao deve aparecer em trabalhista"
    assert "CTN art. 174" not in p, "CTN art. 174 (fiscal) nao deve aparecer em trabalhista"
    assert "credito tributario" not in p, "credito tributario (fiscal) nao deve aparecer em trabalhista"
    assert "pre-executividade" not in p, "Pre-executividade (fiscal) nao deve aparecer em trabalhista"


def test_rules_civel_keywords():
    """Variant civel contem termos paradigmaticos civeis (STJ Tema repetitivo,
    Sumula STJ, REsp/RE, AREsp, Cumprimento de Sentenca) e NAO contem termos
    fiscal/trab-exclusivos."""
    p = _build_rules("civel")
    # Civel-specific paradigms
    assert "STJ" in p
    assert "REsp" in p, "Civel deve citar REsp (Recurso Especial)"
    assert "Tema repetitivo" in p, "Civel deve mencionar Tema repetitivo STJ (CPC art. 927)"
    assert "Sumula" in p and "STJ" in p, "Civel deve referenciar Sumulas STJ"
    assert "Cumprimento de Sentenca" in p or "cumprimento de sentenca" in p.lower(), (
        "Civel deve mencionar Cumprimento de Sentenca (CPC art. 523+)"
    )
    assert "AREsp" in p, "Civel deve listar AREsp como recurso processual"
    # Fiscal/Trab-exclusive devem estar AUSENTES
    assert "CTN art. 174" not in p, "CTN art. 174 (fiscal) nao deve aparecer em civel"
    assert "AIRR" not in p, "AIRR (trabalhista) nao deve aparecer em civel"
    assert "Sumula 331 TST" not in p, "Sumula 331 TST nao deve aparecer em civel"
    assert "pre-executividade" not in p, "Pre-executividade (fiscal) nao deve aparecer em civel"


def test_rules_misto_keywords_and_confidence():
    """Variant misto e abstrato (regras condicionais, sem vocabulario
    fiscal/trab/civel ancorado), e introduz Regra E -0.10 confidence."""
    p = _build_rules("misto")
    # Misto deve ter Regra E explicita sobre reducao de confidence
    assert "0.10" in p, "Misto deve ter Regra E reduzindo confidence em 0.10"
    assert "MISTO" in p or "misto" in p
    assert "incerteza" in p, "Misto deve justificar reducao por incerteza estrutural"
    # Vocabulario CONDICIONAL por tipo de processo. Morava na Regra G (FISCAL/
    # TRABALHISTA/CIVEL em caixa alta), que saiu com a juris em a0a82f8; o
    # condicional sobreviveu na NOTA da ESCALA misto. Espaco normalizado porque a
    # frase quebra linha no meio.
    norm = " ".join(p.split())
    assert "pra processo fiscal use vocabulario fiscal" in norm, "Misto condicional: fiscal"
    assert "pra trabalhista use TST/RR" in norm, "Misto condicional: trabalhista"
    assert "pra civel use STJ/REsp" in norm, "Misto condicional: civel"


# ── Integration: prompt completo dispatch corretamente ─────────────────────


@pytest.mark.parametrize(
    "tipo,must_contain,must_not_contain",
    [
        # "Anulatoria" nao serve como marker exclusivo: aparece no _REGRA_H1_COMUM (shared).
        # Idem "pro_fazenda_firmado" e "Execucao Fiscal" no prompt COMPLETO (blocos comuns).
        # Tema 372/725 e DIFAL sairam com a juris do L3 (a0a82f8) — ver o bloco acima.
        ("fiscal", ["pre-executividade", "CTN art. 174", "credito tributario"], ["AIRR", "AREsp", "deposito recursal"]),
        ("trabalhista", ["AIRR", "Sumula 331 TST", "deposito recursal"], ["CTN art. 174", "credito tributario", "pre-executividade"]),
        ("civel", ["AREsp", "Tema repetitivo"], ["AIRR", "CTN art. 174", "pre-executividade"]),
    ],
)
def test_prompt_dispatch_by_dominant_tipo(tipo, must_contain, must_not_contain):
    """End-to-end: req com 3 procs do mesmo tipo gera prompt com vocabulario
    correto e sem cross-contamination de outros tipos."""
    req = MeritoSynthesisRequest(
        merito_id=1,
        merito_context="monit_poletto",
        processo_syntheses=[_ps(tipo)] * 3,
    )
    p = build_merito_synthesis_prompt(req)
    for term in must_contain:
        assert term in p, f"prompt {tipo}-dominante deve conter '{term}'"
    for term in must_not_contain:
        assert term not in p, f"prompt {tipo}-dominante NAO deve conter '{term}' (cross-contamination)"


def test_prompt_misto_when_below_threshold():
    """3 fiscal + 1 civel (75%, abaixo de 80%) -> prompt misto (regra E -0.10)."""
    req = MeritoSynthesisRequest(
        merito_id=1,
        merito_context="monit_poletto",
        processo_syntheses=[_ps("fiscal")] * 3 + [_ps("civel")],
    )
    p = build_merito_synthesis_prompt(req)
    # Confirma routing pra misto via marker exclusivo
    assert "MERITO MISTO" in p or "merito misto" in p.lower() or "Regra E" in p, (
        "Quando dominancia <80%, prompt deve ser variant misto (com Regra E -0.10)"
    )
    assert "0.10" in p

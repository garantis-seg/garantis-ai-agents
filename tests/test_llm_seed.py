"""Seed determinístico do cascade (L2/L3) — prova de reprodutibilidade.

O ponto do #2 (convergência da volatilidade): mesmo input → mesmo seed → mesma
banda N×. Estes testes provam a parte determinística (o seed), sem queimar call
LLM. A prova empírica end-to-end (banda N× estável) é o harness L3-only.
"""
import os

import pytest

from src.agents._utils.llm_seed import _SEED_FLAG, deterministic_seed, seed_for


def test_seed_estavel_para_mesmas_parts():
    a = deterministic_seed("merito_synthesis", 680165, None, "prompt-XYZ")
    b = deterministic_seed("merito_synthesis", 680165, None, "prompt-XYZ")
    assert a == b  # reprodutível — a base de "mesmo input -> mesma banda"


def test_seed_varia_com_input():
    a = deterministic_seed("merito_synthesis", 680165, None, "prompt-XYZ")
    c = deterministic_seed("merito_synthesis", 680165, None, "prompt-DIFERENTE")
    assert a != c


def test_seed_int32_positivo():
    # Range aceito pelo Gemini (Union[int, None]; mascarado p/ int32 positivo).
    for parts in [("x",), ("merito_synthesis", 1), ("p", "x" * 100000)]:
        s = deterministic_seed(*parts)
        assert isinstance(s, int) and 0 <= s <= 0x7FFFFFFF


def test_seed_nao_e_hash_builtin_salgado():
    # hash() builtin é salgado por processo (PYTHONHASHSEED) → quebraria a
    # reprodutibilidade cross-container. Valor conhecido prova SHA-256 estável.
    assert deterministic_seed("a", "b") == deterministic_seed("a", "b")
    # separador \x1f evita colisão de concatenação ("ab" vs "a","b").
    assert deterministic_seed("a", "b") != deterministic_seed("ab")


def test_seed_for_respeita_flag(monkeypatch):
    monkeypatch.setenv(_SEED_FLAG, "true")
    assert seed_for("x") == deterministic_seed("x")
    monkeypatch.setenv(_SEED_FLAG, "false")
    assert seed_for("x") is None  # OFF → seed aleatório (comportamento legado)


def test_seed_for_default_off(monkeypatch):
    # default OFF (ship inerte + flip explícito): ausência do env var → None.
    monkeypatch.delenv(_SEED_FLAG, raising=False)
    assert seed_for("x") is None


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))

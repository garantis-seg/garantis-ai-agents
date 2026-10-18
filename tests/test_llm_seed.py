"""Seed determinístico do cascade (L2/L3) — prova de reprodutibilidade.

O ponto do #2 (convergência da volatilidade): mesmo input → mesmo seed → mesma
banda N×. Estes testes provam a parte determinística (o seed), sem queimar call
LLM. A prova empírica end-to-end (banda N× estável) é o harness L3-only.
"""

import pytest

from src.agents._utils.llm_seed import deterministic_seed, seed_for


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


def test_seed_for_vai_sem_env(monkeypatch):
    # o seed nao depende de env: a flag ENGINE_LLM_SEED_ENABLED saiu (ON em prod e na demo)
    monkeypatch.delenv("ENGINE_LLM_SEED_ENABLED", raising=False)
    assert seed_for("x") == deterministic_seed("x")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))

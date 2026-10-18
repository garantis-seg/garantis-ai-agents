"""O bloco "probabilidade_exito e contexto" entra sempre no prompt do L3.

O `BLOQUEIO_PROB_EXITO_ENABLED` valia true em prod e na demo, e o default do codigo era
ON. A flag saiu: nem o valor false tira o bloco.
"""
from src.agents.merito_synthesis.prompts import _build_bloqueio_prob_exito


def test_a_env_nao_tira_mais_o_bloco(monkeypatch):
    monkeypatch.setenv("BLOQUEIO_PROB_EXITO_ENABLED", "false")
    assert _build_bloqueio_prob_exito().startswith(
        "=== PROBABILIDADE_EXITO = CONTEXTO, NAO DECIDE O NIVEL ==="
    )

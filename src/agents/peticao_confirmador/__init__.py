"""Peticao Confirmador Agent (C5 -- o confirmador COMPARATIVO da peticao inicial).

UMA chamada LLM barata que julga os N candidatos JUNTOS e responde o INDICE do que
e a peca inaugural deste processo -- ou 0 (NENHUM), que e resposta certa e esperada.

⛔ O texto do prompt e VERBATIM do arnes que mediu a camada -- o placar e o porque
estao no docstring de `prompts.py`.
"""

from .agent import PROMPT_VERSION, confirmar_peticao
from .schemas import (
    CONFIRMADOR_RESPONSE_SCHEMA,
    CandidatoConfirmador,
    ConfirmadorCard,
    ConfirmadorRequest,
    ConfirmadorResponse,
    ProcessoConfirmador,
)

__all__ = [
    "CONFIRMADOR_RESPONSE_SCHEMA",
    "PROMPT_VERSION",
    "CandidatoConfirmador",
    "ConfirmadorCard",
    "ConfirmadorRequest",
    "ConfirmadorResponse",
    "ProcessoConfirmador",
    "confirmar_peticao",
]

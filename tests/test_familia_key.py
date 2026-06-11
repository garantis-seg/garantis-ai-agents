# -*- coding: utf-8 -*-
"""Truth-table do roteamento de família do vocab v4 (_familia_key).

Origem: censo do prompt-review 2026-06-10 achou Execução Fiscal roteada pro vocab
TRABALHISTA quando a classe vem como tree-path CNJ ("1116 - PROCESSO CÍVEL E DO
TRABALHO -> ... -> Execução Fiscal") — o cabeçalho contém 'TRABALHO' pra qualquer
classe. Fix: com '->' na classe, só o último segmento entra no match.
"""
import pytest

from src.agents.mov_factsheet.prompts_v4 import _familia_key


@pytest.mark.parametrize(
    "materia,classe,esperado",
    [
        # casos planos (comportamento pré-existente, não pode mudar)
        (None, "Execução Fiscal", "fiscal"),
        ("Tributário", "Agravo de Instrumento", "fiscal"),
        ("Trabalhista", None, "trabalhista"),
        (None, "Reclamação Trabalhista", "trabalhista"),
        (None, "Procedimento Comum Cível", "civel"),
        (None, None, "civel"),
        ("Civel", "Apelação", "civel"),
        # tree-path CNJ — o bug do censo (proc 5159436-51.2025.8.09.0051/TJGO)
        (None, "1116 - PROCESSO CÍVEL E DO TRABALHO -> Processo de Execução -> Execução Fiscal", "fiscal"),
        ("Tributário", "1116 - PROCESSO CÍVEL E DO TRABALHO -> Processo de Execução -> Execução Fiscal", "fiscal"),
        # tree-path de classe genuinamente trabalhista segue trabalhista
        (None, "985 - PROCESSO DO TRABALHO -> Rito Ordinário -> Reclamação Trabalhista", "trabalhista"),
        # tree-path cível NÃO pode mais cair em trabalhista pelo header
        (None, "7 - PROCESSO CÍVEL E DO TRABALHO -> Processo de Conhecimento -> Procedimento Comum Cível", "civel"),
        # matéria continua mandando mesmo com tree-path genérico
        ("Trabalhista", "7 - PROCESSO CÍVEL E DO TRABALHO -> Processo de Conhecimento -> Procedimento Comum", "trabalhista"),
    ],
)
def test_familia_key(materia, classe, esperado):
    assert _familia_key({"materia": materia, "classe": classe}) == esperado

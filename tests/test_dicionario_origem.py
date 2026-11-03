"""Dicionário fechado da origem do S2c (decisão do Alfredo, 03/11/2026).

Funções puras. Cada teste tem o caso que casa e o caso que não casa.
"""
from __future__ import annotations

import pytest

from src.agents.qualificador_conexo import dicionario_origem as d
from src.agents.qualificador_conexo import prompts


# ── expressoes_no_trecho e tipo_do_trecho ───────────────────────────────────

@pytest.mark.parametrize("trecho,tipo", [
    ("Trata-se de AUTO DE INFRAÇÃO de IRPJ.", "auto_de_infracao"),
    ("lancamento de oficio da multa", "auto_de_infracao"),            # sem acento
    ("Julgar improcedente a   impugnação.", "auto_de_infracao"),      # espaço repetido
    ("Notificação de Lançamento nº 123", "auto_de_infracao"),
    ("O Despacho Decisório não homologou.", "despacho_decisorio"),
    ("PER/DCOMP nº 12345.67890", "despacho_decisorio"),
    ("pedido de ressarcimento de IPI", "despacho_decisorio"),
    ("compensação não homologada", "despacho_decisorio"),
    ("Manifestação de Inconformidade apresentada.", "despacho_decisorio"),
    ("AIIM nº 4.123.456-7", "aiim"),
    ("Auto de Infração e Imposição de Multa nº 4.123.456", "aiim"),
])
def test_tipo_do_trecho_positivo(trecho, tipo):
    assert d.tipo_do_trecho(trecho) == tipo


@pytest.mark.parametrize("trecho", [
    "",
    "Acórdão de recurso voluntário. Nego provimento.",
    "impugnações diversas",                      # plural não é a expressão
    "autos de infração",                         # plural não é a expressão
    "a empresa caiim teste",                     # AIIM dentro de outra palavra
    "PERDCOMP",                                  # grafia fora do dicionário
])
def test_tipo_do_trecho_negativo(trecho):
    assert d.tipo_do_trecho(trecho) is None


def test_aiim_longo_nao_conta_para_auto_de_infracao():
    trecho = "Auto de Infração e Imposição de Multa lavrado pela Fazenda."
    assert d.expressoes_no_trecho(trecho) == {
        "aiim": ["auto de infração e imposição de multa"]}
    assert d.tipos_no_trecho(trecho) == {"aiim"}
    # controle: o "auto de infração" sozinho continua federal
    assert d.tipos_no_trecho("Auto de Infração lavrado pela Receita.") == {"auto_de_infracao"}


def test_aiim_com_expressao_federal_fica_null():
    trecho = "AIIM nº 1. Ver também o despacho decisório."
    assert d.tipos_no_trecho(trecho) == {"aiim", "despacho_decisorio"}
    assert d.tipo_do_trecho(trecho) is None


def test_aiim_com_palavra_de_defesa_prova_aiim():
    # A defesa é palavra fraca: ela não briga com aiim (TIT-SP).
    assert d.tipo_do_trecho("AIIM nº 4.123.456 ... a impugnação apresentada") == "aiim"
    assert d.tipo_do_trecho(
        "Auto de Infração e Imposição de Multa. Manifestação de inconformidade.") == "aiim"


@pytest.mark.parametrize("trecho", [
    "AIIM ... despacho decisório",
    "AIIM nº 1 e o auto de infração federal, com impugnação",
    "AIIM e lançamento de ofício",
    "AIIM e PER/DCOMP",
])
def test_aiim_com_expressao_federal_forte_nao_prova_nada(trecho):
    assert d.tipo_do_trecho(trecho) is None


def test_empate_federal_a_impugnacao_decide_auto():
    trecho = ("Multa isolada sobre declaração de compensação. "
              "A contribuinte apresentou impugnação.")
    assert d.tipos_no_trecho(trecho) == {"auto_de_infracao", "despacho_decisorio"}
    assert d.tipo_do_trecho(trecho) == "auto_de_infracao"


def test_empate_federal_a_manifestacao_decide_despacho():
    trecho = ("Lançamento de ofício citado. "
              "A contribuinte apresentou manifestação de inconformidade.")
    assert d.tipo_do_trecho(trecho) == "despacho_decisorio"


def test_empate_federal_sem_defesa_ou_com_as_2_defesas_fica_null():
    assert d.tipo_do_trecho("Auto de infração e pedido de restituição.") is None
    assert d.tipo_do_trecho("impugnação e manifestação de inconformidade") is None


def test_dicionario_fechado_tem_os_3_tipos_do_schema():
    from typing import get_args

    from src.agents.qualificador_conexo.schemas import TipoOrigem

    assert set(d.EXPRESSOES_ORIGEM) == set(get_args(TipoOrigem))
    for tipo, defesa in d.DEFESA_DE_1A_INSTANCIA.items():
        assert defesa in d.EXPRESSOES_ORIGEM[tipo]


# ── o prompt renderiza o dicionário da constante ────────────────────────────

def _prompts(modo_capa: bool = False) -> tuple[str, str]:
    a = prompts.build_decisao_prompt(dados={}, achados=[], menu=["pedir_pagina"],
                                     budget_restante=5, budget_por_item=3)
    b = prompts.build_emissao_prompt(dados={}, achados=[], modo_capa=modo_capa)
    return a, b


def test_prompt_traz_o_dicionario_inteiro_e_a_regra_do_null():
    for p in _prompts():
        assert "<guia_origem>" in p
        assert d.render_dicionario() in p
        for exps in d.EXPRESSOES_ORIGEM.values():
            for exp in exps:
                assert f'"{exp}"' in p
        assert ("Sem uma expressão do dicionário num trecho literal, "
                "origem.tipo = null.") in p


def test_prompt_le_a_constante_controle_positivo(monkeypatch):
    # Controle positivo: uma expressão plantada na constante aparece no prompt.
    # Um dicionário redigitado no prompt não mostraria a expressão plantada.
    plantado = {**d.EXPRESSOES_ORIGEM,
                "aiim": (*d.EXPRESSOES_ORIGEM["aiim"], "expressao-plantada-xyz")}
    monkeypatch.setattr(d, "EXPRESSOES_ORIGEM", plantado)
    for p in _prompts():
        assert '"expressao-plantada-xyz"' in p
    assert d.tipo_do_trecho("tem expressao-plantada-xyz aqui") == "aiim"


def test_prompt_documentos_pede_prova_na_origem():
    _, b = _prompts()
    assert '"origem": {"tipo": "auto_de_infracao|despacho_decisorio|aiim|null", ' \
           '"data": "AAAA-MM-DD|null", "prova": {"doc_id"' in b


def test_modo_capa_nao_recebe_o_guia_da_origem():
    _, b = _prompts(modo_capa=True)
    assert "<modo_capa>" in b and "<guia_origem>" not in b

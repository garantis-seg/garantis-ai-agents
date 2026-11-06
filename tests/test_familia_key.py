# -*- coding: utf-8 -*-
"""A familia do L1 vem pronta no payload. Este servico nao tem banco e nao classifica.

A escada que resolve a familia mora em `garantis_shared.materia.classificar_materia`, com os
testes dela no shared.
"""
import pytest

from src.agents._raw_templates import get_raw_prompt_templates
from src.agents.mov_factsheet.prompts_v4 import VOCAB_FAMILIA, _familia_key
from src.agents.mov_factsheet.schemas import ProcessoContext


@pytest.mark.parametrize("familia", ["fiscal", "trabalhista", "civel"])
def test_a_familia_do_payload_vence_a_materia_e_a_classe(familia):
    assert _familia_key({
        "familia": familia, "materia": "Dívida Ativa", "classe": "Reclamação Trabalhista",
    }) == familia
    assert _familia_key(ProcessoContext(cnj="0", familia=familia)) == familia


@pytest.mark.parametrize("processo", [
    {"cnj": "0001234-56.2020.8.26.0053"},
    {"cnj": "0001234-56.2020.8.26.0053", "familia": None},
    {"cnj": "0001234-56.2020.8.26.0053", "familia": ""},
    {"cnj": "0001234-56.2020.8.26.0053", "familia": "tributario"},
    {"cnj": "0001234-56.2020.8.26.0053", "materia": "Tributário", "classe": "Execução Fiscal"},
])
def test_sem_familia_valida_o_prompt_nao_sai(processo):
    with pytest.raises(ValueError, match="payload sem familia"):
        _familia_key(processo)


def test_o_vocabulario_tem_as_3_familias_do_shared():
    assert set(VOCAB_FAMILIA) == {"fiscal", "trabalhista", "civel"}


def test_o_template_raw_do_l1_sai_sem_erro():
    """O template monta o processo sem o shared. Sem a familia, a aba "Prompt Raw" mostraria
    a string de erro do builder no lugar do prompt."""
    template = get_raw_prompt_templates()["layer1_mov_factsheet"]
    assert "{{classe}}" in template and "erro ao gerar" not in template

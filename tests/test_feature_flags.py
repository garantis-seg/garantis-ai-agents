"""`flag_enabled`: o conjunto de ACEITE e o de REJEICAO.

⭐ Este arquivo nasceu em 2026-08-27 (card 869entgbc) recolhendo um parametrize que
estava em `test_decisao_exige_corpo.py` como `test_flag_desligada_em_qualquer_forma`.
Quando a flag `L1_DECISAO_EXIGE_CORPO` virou permanente, todos os testes de "flag OFF"
daquele arquivo sairam — mas AQUELE nao era um teste da trava de corpo, era o **unico
oraculo das formas negativas do parser** em todo o repo (medido: nenhum outro teste
exercita `""` / `"false"` / `"0"` / `"no"`). Apaga-lo junto com os irmaos teria removido
cobertura de um helper COMPARTILHADO por acidente de vizinhanca.

⛔ Nao devolva estes casos pra dentro do teste de uma feature: o proximo que aposentar
aquela feature apaga o parser junto, de novo.
"""
import pytest

from src.agents._utils.feature_flags import flag_enabled

_FLAG = "TEST_FLAG_ENABLED_ORACULO"


@pytest.mark.parametrize("valor", ["true", "TRUE", "True", "1", "yes", "on", " true "])
def test_formas_que_LIGAM(monkeypatch, valor):
    monkeypatch.setenv(_FLAG, valor)
    assert flag_enabled(_FLAG) is True


@pytest.mark.parametrize("valor", ["", "false", "0", "no", "off", "sim", "2"])
def test_formas_que_NAO_ligam(monkeypatch, valor):
    """⛔ `off` e `sim` estao aqui de proposito: o parser e uma ALLOWLIST de 4 formas,
    nao uma blocklist. Qualquer coisa fora do conjunto e False — inclusive um `sim` que
    alguem escreveria achando que liga."""
    monkeypatch.setenv(_FLAG, valor)
    assert flag_enabled(_FLAG) is False


def test_ausente_usa_o_default_e_o_default_e_OFF(monkeypatch):
    monkeypatch.delenv(_FLAG, raising=False)
    assert flag_enabled(_FLAG) is False
    assert flag_enabled(_FLAG, default="true") is True

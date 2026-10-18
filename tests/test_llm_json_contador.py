"""O contador `FALLBACK_DISPAROU familia=llm_json_conserto` do `parse_llm_json`.

Ele conta so o conserto que MUDA o texto, e diz quem chamou. O JSON limpo nao conta: sem
isso, a contagem no D+21 nao separa o agente que precisa do conserto do que nao precisa.
"""
from __future__ import annotations

import logging

import pytest

from src.utils.llm_json import parse_llm_json

_LOGGER = "src.utils.llm_json"


def test_json_limpo_nao_conta(caplog):
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        assert parse_llm_json('  {"a": 1}\n') == {"a": 1}
    assert "FALLBACK_DISPAROU" not in caplog.text


@pytest.mark.parametrize("raw, esperado, conserto", [
    ('```json\n{"a": 1}\n```', {"a": 1}, "cerca"),
    ('{"a": 1} lixo', {"a": 1}, "extra_data"),
    ('{"a": 1, "b": "corta', {"a": 1}, "string_aberta"),
    ('{"a": 1}}', {"a": 1}, "extra_data"),
    ('[{"a": 1}]', {"a": 1}, "lista"),
])
def test_conserto_conta_com_o_tipo_e_o_chamador(caplog, raw, esperado, conserto):
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        assert parse_llm_json(raw) == esperado
    assert (
        f"FALLBACK_DISPAROU familia=llm_json_conserto conserto={conserto} "
        f"chamador={__name__}"
    ) in caplog.text


def test_conserto_que_falha_levanta_sem_contar(caplog):
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        with pytest.raises(ValueError):
            parse_llm_json('{"a": "corta')
    assert "FALLBACK_DISPAROU" not in caplog.text

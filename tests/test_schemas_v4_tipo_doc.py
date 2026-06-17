# -*- coding: utf-8 -*-
"""Coerção tipo_doc fora-da-taxonomia -> 'outros' (fix 2026-06-17).

A LLM emite tipo_doc fora dos 34 valores (ex 'relatorio_fiscal' em exec-fiscal, sem
constrained-decoding no ramo não-petição). Sem a coerção o parse falha com pydantic
`literal_error` -> 500 -> retry storm do L1; em mérito de 1 mov vira 100% L1 fail ->
l1_degraded -> indeterminado (raiz dos 9 méritos travados em 2026-06-17). Estes testes
travam o invariante sem chamar LLM.
"""
from src.agents.mov_factsheet.schemas_v4 import MovFactSheetCardV4


def _base(**over):
    d = dict(
        resumo_ato="Juntada de relatorio fiscal.",
        tipo_doc="sentenca",
        relevancia_merito="baixa",
    )
    d.update(over)
    return d


def test_unknown_tipo_doc_coerced_to_outros():
    # Valor real visto em prod (input_value='relatorio_fiscal') -> 'outros', sem crash.
    card = MovFactSheetCardV4(**_base(tipo_doc="relatorio_fiscal"))
    assert card.tipo_doc == "outros"


def test_known_tipo_doc_preserved():
    # Valor válido NÃO é tocado pela coerção.
    card = MovFactSheetCardV4(**_base(tipo_doc="acordao"))
    assert card.tipo_doc == "acordao"


def test_peticao_subclass_inherits_tipo_doc_coercion():
    # field_validator herdado pela subclasse (pydantic v2), como o de null-blocks.
    from src.agents.mov_factsheet.schemas_v4 import PeticaoExtractCardV4

    card = PeticaoExtractCardV4(**_base(tipo_doc="auto_infracao"))
    assert card.tipo_doc == "outros"

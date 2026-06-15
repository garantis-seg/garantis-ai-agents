# -*- coding: utf-8 -*-
"""Coerção null->default dos blocos aninhados do MovFactSheetCardV4 (fix 2026-06-15).

O Gemini às vezes emite decisao/evento_garantia/valores como null EXPLÍCITO (chave
presente, valor None). Sem a coerção, o parse falha com pydantic `model_type`
("Input should be a valid dictionary or instance of <Block>") -> 500 -> retry storm
do L1 (erro DOMINANTE do cascade, ~56% dos 500 do ai-agents). Estes testes travam o
invariante sem chamar LLM.
"""
from src.agents.mov_factsheet.schemas_v4 import (
    DecisaoBlockV4,
    EventoGarantiaV4,
    MovFactSheetCardV4,
    ValoresBlockV4,
)


def _base(**over):
    d = dict(
        resumo_ato="Sentenca de procedencia.",
        tipo_doc="sentenca",
        relevancia_merito="alta",
    )
    d.update(over)
    return d


def test_null_blocks_coerced_to_default():
    # Gemini emite os 3 blocos como null explicito -> coercao para bloco default.
    card = MovFactSheetCardV4(
        **_base(decisao=None, evento_garantia=None, valores=None)
    )
    assert isinstance(card.decisao, DecisaoBlockV4)
    assert isinstance(card.evento_garantia, EventoGarantiaV4)
    assert isinstance(card.valores, ValoresBlockV4)
    assert card.decisao.tem_decisao is False
    assert card.evento_garantia.tipo == "nenhum"
    assert card.valores.valor_garantia is None


def test_absent_blocks_still_default():
    # Sem as chaves: default_factory (comportamento pre-fix preservado).
    card = MovFactSheetCardV4(**_base())
    assert isinstance(card.decisao, DecisaoBlockV4)
    assert card.evento_garantia.tipo == "nenhum"


def test_real_block_values_preserved():
    # Bloco com conteudo real NAO e zerado pela coercao (so None vira default).
    card = MovFactSheetCardV4(
        **_base(
            decisao={"tem_decisao": True, "natureza": "procedente"},
            evento_garantia={"tipo": "acionamento"},
        )
    )
    assert card.decisao.tem_decisao is True
    assert card.decisao.natureza == "procedente"
    assert card.evento_garantia.tipo == "acionamento"


def test_peticao_subclass_inherits_coercion():
    # field_validator e herdado pela subclasse (pydantic v2). PeticaoExtractCardV4
    # tem campos extras com default, entao _base() basta.
    from src.agents.mov_factsheet.schemas_v4 import PeticaoExtractCardV4

    card = PeticaoExtractCardV4(
        **_base(decisao=None, evento_garantia=None, valores=None)
    )
    assert isinstance(card.decisao, DecisaoBlockV4)
    assert isinstance(card.evento_garantia, EventoGarantiaV4)

# -*- coding: utf-8 -*-
"""A petição inicial diz se a ação discute um DÉBITO ou pede um CRÉDITO.

⚠️ Guarda FRACA por natureza, como a do valor da causa: quem decide é a LLM. O consumidor é o
frontend-api, que agrega a resposta das petições do conexo na chave `existe_debito` do
callback ao parceiro e descarta a resposta sem evidência. Aqui trava-se o que dá pra travar:

  · o pedido ESTÁ nas DUAS prompts — o `PeticaoExtractCardV4` é COMPARTILHADO entre o 1P
    e o 1X, e campo que a prompt não explica, sob constrained decoding, é pior que campo
    ausente;
  · o 1X, que lê QUALQUER documento, restringe o campo à petição inicial;
  · o NOME e os VALORES são os que o frontend-api lê (`conexos_engine.garantia`) — renomear
    aqui cala a chave lá, sem erro;
  · os 2 campos são OPCIONAIS, e a evidência sai ANTES da resposta;
  · a peça CHUNKADA (>180k) não perde o par no `reduce_peca_cards`.
"""
from typing import get_args

import pytest

from src.agents.mov_factsheet.chunking import reduce_peca_cards
from src.agents.mov_factsheet.prompts_v4 import (
    _build_doc_incerto_prompt_v4,
    build_mov_factsheet_prompt_v4,
)
from src.agents.mov_factsheet.schemas import DocAnexado, MovInput, ProcessoContext
from src.agents.mov_factsheet.schemas_v4 import PeticaoExtractCardV4


@pytest.fixture
def _ctx():
    return ProcessoContext(cnj="5026352-10.2026.4.03.6100", classe="Procedimento Comum Civel",
                           polo_ativo="NESTLE BRASIL LTDA", polo_passivo="UNIAO FEDERAL",
                           materia="Tributario")


@pytest.fixture
def _doc():
    return DocAnexado(doc_key="pet-1", tipo="1", titulo="PETICAO INICIAL",
                      data_documento="2026-05-04", provider="escavador",
                      text_content="Requer a anulacao da decisao que negou a restituicao.")


def _prompt_1p(ctx, doc):
    return build_mov_factsheet_prompt_v4(ctx, MovInput(mov_id="pet-1", texto=""),
                                         documentos_anexados=[doc], classe="peticao")


def _prompt_1x(ctx, doc):
    return _build_doc_incerto_prompt_v4(ctx, MovInput(mov_id="pet-1", texto=""),
                                        documentos_anexados=[doc])


@pytest.mark.parametrize("build", [_prompt_1p, _prompt_1x], ids=["1P", "1X"])
def test_as_DUAS_prompts_pedem_a_resposta_COM_evidencia(_ctx, _doc, build):
    p = build(_ctx, _doc)
    assert "debito_ou_credito" in p and "debito_ou_credito_evidencia" in p
    assert "DESCARTADA" in p
    # O ponto mais traiçoeiro: o "crédito" do fisco é o débito da empresa.
    assert "'crédito tributário'" in p
    # E o desempate do pedido que pede crédito E discute débito (o PER/DCOMP não homologado).
    assert "MISTO" in p


def test_o_1X_so_responde_na_PETICAO_INICIAL(_ctx, _doc):
    """Sentença e decisão narram o pedido; o 1X as lê."""
    assert "debito_ou_credito: SÓ se o documento for a PETIÇÃO INICIAL" in _prompt_1x(_ctx, _doc)


def test_o_nome_e_os_valores_sao_os_que_o_frontend_api_le():
    """Oráculo re-digitado de propósito: é o literal do lado do frontend-api."""
    f = PeticaoExtractCardV4.model_fields["debito_ou_credito"]
    valores = {a for a in get_args(get_args(f.annotation)[0])}
    assert valores == {"debito", "credito", "incerto"}
    assert "debito_ou_credito_evidencia" in PeticaoExtractCardV4.model_fields


def test_os_campos_sao_OPCIONAIS_e_a_evidencia_vem_ANTES():
    for campo in ("debito_ou_credito", "debito_ou_credito_evidencia"):
        f = PeticaoExtractCardV4.model_fields[campo]
        assert not f.is_required() and f.default is None
    ordem = list(PeticaoExtractCardV4.model_fields)
    assert ordem.index("debito_ou_credito_evidencia") < ordem.index("debito_ou_credito")


_BASE = {"cdas": [], "processos_citados": [], "tipo_doc": "peticao_inicial"}


def _dc(resposta, evidencia):
    return {**_BASE, "debito_ou_credito": resposta, "debito_ou_credito_evidencia": evidencia}


@pytest.mark.parametrize("caso,cards,esperado", [
    ("o pedido no 1o pedaco, so anexos no ultimo",
     [_dc("debito", "do pedido"), dict(_BASE), _dc("incerto", None)], ("debito", "do pedido")),
    ("o formulario de credito no ultimo nao apaga o debito",
     [_dc("debito", "do pedido"), _dc("credito", "do formulario")], ("debito", "do pedido")),
    ("credito vence incerto", [_dc("incerto", None), _dc("credito", "do pedido")],
     ("credito", "do pedido")),
    ("no empate, o pedaco COM evidencia", [_dc("debito", None), _dc("debito", "trecho")],
     ("debito", "trecho")),
    ("nenhum pedaco respondeu", [dict(_BASE), dict(_BASE)], (None, None)),
])
def test_a_peca_CHUNKADA_leva_a_resposta_mais_FORTE(caso, cards, esperado):
    """⛔ MUTANTES: tirar o par do `reduce_peca_cards` (a lista de campos dele é FECHADA), ou
    voltar a pegar o ÚLTIMO pedaço — a posição não diz onde está o pedido."""
    out = reduce_peca_cards(cards)
    assert (out["debito_ou_credito"], out["debito_ou_credito_evidencia"]) == esperado, caso

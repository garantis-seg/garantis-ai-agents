# -*- coding: utf-8 -*-
"""O valor da causa DECLARADO pela petição (card 869f4gupy, 2026-09-28).

⚠️ Guarda FRACA por natureza, como a do `tit_sp`: quem decide o valor é a LLM, e o guard
de verdade (âncora + declaração antes do número + só petição inicial) mora no sink do
garantis-shared (`peticao_sink.valor_causa_ok`). Aqui trava-se o que dá pra travar:

  · o pedido ESTÁ nas DUAS prompts — o `PeticaoExtractCardV4` é COMPARTILHADO entre o 1P
    e o 1X, e campo que a prompt não explica, sob constrained decoding, é pior que campo
    ausente;
  · o 1X, que lê QUALQUER documento, restringe o campo à petição inicial;
  · os 2 campos são OPCIONAIS: o card cacheado de antes deles continua válido;
  · a peça CHUNKADA (>180k) não perde o par no `reduce_peca_cards`.
"""
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
    return ProcessoContext(cnj="1055745-25.2024.4.01.3400", classe="Mandado de Seguranca Civel",
                           polo_ativo="VOLKSWAGEN DO BRASIL", polo_passivo="UNIAO FEDERAL",
                           materia="Tributario")


@pytest.fixture
def _doc():
    return DocAnexado(doc_key="pet-1", tipo="1", titulo="PETICAO INICIAL",
                      data_documento="2024-07-29", provider="escavador",
                      text_content="Da-se a causa o valor de R$ 1.000,00.")


def _prompt_1p(ctx, doc):
    return build_mov_factsheet_prompt_v4(ctx, MovInput(mov_id="pet-1", texto=""),
                                         documentos_anexados=[doc], classe="peticao")


def _prompt_1x(ctx, doc):
    return _build_doc_incerto_prompt_v4(ctx, MovInput(mov_id="pet-1", texto=""),
                                        documentos_anexados=[doc])


@pytest.mark.parametrize("build", [_prompt_1p, _prompt_1x], ids=["1P", "1X"])
def test_as_DUAS_prompts_pedem_o_valor_COM_evidencia_e_a_emenda_prevalece(_ctx, _doc, build):
    p = build(_ctx, _doc)
    assert "valor_causa_declarado" in p and "valor_causa_evidencia" in p
    assert "EMENDA" in p and "DESCARTADO" in p


def test_o_1X_so_aceita_o_valor_da_PETICAO_INICIAL(_ctx, _doc):
    """Sentença e decisão CITAM o valor da causa no relatório; o 1X as lê."""
    assert "SÓ se o documento for a PETIÇÃO INICIAL" in _prompt_1x(_ctx, _doc)


def test_os_campos_sao_OPCIONAIS_e_o_card_antigo_segue_valido():
    for campo in ("valor_causa_declarado", "valor_causa_evidencia"):
        f = PeticaoExtractCardV4.model_fields[campo]
        assert not f.is_required() and f.default is None


def test_a_peca_CHUNKADA_leva_o_par_do_ULTIMO_chunk_que_declarou():
    """⛔ MUTANTE: tirar o par do `reduce_peca_cards` — review adversarial de 28/09.

    O reduce monta o card com lista FECHADA de campos, e já tinha perdido os admin refs assim
    (medido 2026-08-05). A declaração mora no FIM da peça, e a emenda vem depois da inicial."""
    base = {"cdas": [], "processos_citados": [], "tipo_doc": "peticao_inicial"}
    out = reduce_peca_cards([
        {**base, "valor_causa_declarado": 125000.0, "valor_causa_evidencia": "da inicial"},
        dict(base),
        {**base, "valor_causa_declarado": 5782831.97, "valor_causa_evidencia": "da emenda"},
    ])
    assert (out["valor_causa_declarado"], out["valor_causa_evidencia"]) == (5782831.97, "da emenda")
    assert reduce_peca_cards([dict(base), dict(base)])["valor_causa_declarado"] is None

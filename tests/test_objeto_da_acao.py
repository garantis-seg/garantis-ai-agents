# -*- coding: utf-8 -*-
"""A petição inicial diz se a MATÉRIA da ação é FISCAL (`objeto_da_acao`).

O consumidor é o frontend-api (`conexos_resolve.funil._objeto_fiscal`): o 'outro' tira o
`objeto_fiscal` do membro no callback ao parceiro, com ou sem a evidência (ela fica para a
auditoria). ⚠️ Guarda FRACA por natureza: quem decide é a LLM. Aqui trava-se o que dá pra travar,
como no par do débito (`test_debito_ou_credito.py`):

  · o pedido ESTÁ nas DUAS prompts (o `PeticaoExtractCardV4` é COMPARTILHADO entre o 1P e o 1X);
  · a CITAÇÃO não decide: o PA da agência e a ação de origem citados não tornam a ação fiscal;
  · o 1X, que lê QUALQUER documento, restringe o campo à petição inicial;
  · o NOME e os VALORES são os que o frontend-api lê;
  · os 2 campos são OPCIONAIS, e a evidência sai ANTES da resposta;
  · a peça CHUNKADA (>180k) não perde o par, e o 'outro' só vence quando nenhum pedaço disse outra
    coisa (o 'outro' é o erro CARO).
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
    return ProcessoContext(cnj="1002643-43.2024.8.26.0075", classe="Procedimento Comum Civel",
                           polo_ativo="VIACAO BERTIOGA LTDA", polo_passivo="MUNICIPIO DE BERTIOGA",
                           materia="Administrativo", familia="civel")


@pytest.fixture
def _doc():
    return DocAnexado(doc_key="pet-1", tipo="1", titulo="PETICAO INICIAL",
                      data_documento="2024-08-20", provider="escavador",
                      text_content="Requer a indenizacao pelo desequilibrio do contrato de concessao.")


def _prompt_1p(ctx, doc):
    return build_mov_factsheet_prompt_v4(ctx, MovInput(mov_id="pet-1", texto=""),
                                         documentos_anexados=[doc], classe="peticao")


def _prompt_1x(ctx, doc):
    return _build_doc_incerto_prompt_v4(ctx, MovInput(mov_id="pet-1", texto=""),
                                        documentos_anexados=[doc])


#: As 2 regras do texto medido (as 2 prompts e o schema dizem as 2):
#:   · a CITAÇÃO não decide: o PA da licitação, da ANTAQ e do IBAMA e a ação civil pública de origem
#:     faziam fiscais os 4 casos do Kelveng;
#:   · a multa de órgão que não é o fisco é 'outro'.
_REGRAS = ("cita não torna a ação fiscal", "órgão que não é o fisco")


def _texto(s: str) -> str:
    """Sem quebra de linha e sem caixa: a ênfase em maiúscula muda de um texto para o outro."""
    return " ".join(s.split()).lower()


def _bloco(p: str) -> str:
    """O bloco do campo na prompt: de `- objeto_da_acao:` até a PARTE 2. ⛔ A prompt inteira tem
    'na dúvida' em outros blocos (o papel, o tipo e a UF do PA): só o bloco prova a frase do campo."""
    return p.split("- objeto_da_acao:", 1)[1].split("parte 2", 1)[0]


@pytest.mark.parametrize("build", [_prompt_1p, _prompt_1x], ids=["1P", "1X"])
def test_as_DUAS_prompts_pedem_a_resposta_COM_evidencia_e_as_2_regras(_ctx, _doc, build):
    """⛔ MUTANTES: tirar o "na dúvida, 'incerto'" do bloco do 1P ou do 1X."""
    b = _bloco(_texto(build(_ctx, _doc)))
    assert "objeto_da_acao_evidencia" in b
    assert all(r in b for r in _REGRAS), [r for r in _REGRAS if r not in b]
    # O 'outro' é o erro caro: na dúvida, a resposta é 'incerto'.
    assert "na dúvida" in b


def test_a_description_do_schema_diz_a_MESMA_regra_das_prompts():
    """O schema vai no `response_schema` das 2 chamadas. ⛔ MUTANTE: tirar a regra da citação."""
    d = _texto(PeticaoExtractCardV4.model_fields["objeto_da_acao"].description)
    assert all(r in d for r in _REGRAS) and "na dúvida, 'incerto'" in d


def test_o_1X_so_responde_na_PETICAO_INICIAL(_ctx, _doc):
    """Sentença e decisão narram o pedido; o 1X as lê."""
    assert "objeto_da_acao: SÓ se o documento for a PETIÇÃO INICIAL" in _prompt_1x(_ctx, _doc)


def test_o_nome_e_os_valores_sao_os_que_o_frontend_api_le():
    """Oráculo re-digitado de propósito: é o literal do lado do frontend-api."""
    f = PeticaoExtractCardV4.model_fields["objeto_da_acao"]
    assert {a for a in get_args(get_args(f.annotation)[0])} == {"fiscal", "outro", "incerto"}
    assert "objeto_da_acao_evidencia" in PeticaoExtractCardV4.model_fields


def test_os_campos_sao_OPCIONAIS_e_a_evidencia_vem_ANTES():
    for campo in ("objeto_da_acao", "objeto_da_acao_evidencia"):
        f = PeticaoExtractCardV4.model_fields[campo]
        assert not f.is_required() and f.default is None
    ordem = list(PeticaoExtractCardV4.model_fields)
    assert ordem.index("objeto_da_acao_evidencia") < ordem.index("objeto_da_acao")


_BASE = {"cdas": [], "processos_citados": [], "tipo_doc": "peticao_inicial"}


def _oa(resposta, evidencia):
    return {**_BASE, "objeto_da_acao": resposta, "objeto_da_acao_evidencia": evidencia}


@pytest.mark.parametrize("caso,cards,esperado", [
    ("o 'outro' de 1 pedaco nao apaga o 'fiscal' do outro",
     [_oa("outro", "do contrato"), _oa("fiscal", "do ICMS")], ("fiscal", "do ICMS")),
    ("o 'incerto' dos anexos vence o 'outro'",
     [_oa("outro", "do pedido"), _oa("incerto", None)], ("incerto", None)),
    ("todo pedaco disse 'outro'", [_oa("outro", "do pedido"), _oa("outro", None)],
     ("outro", "do pedido")),
    ("o 'fiscal' vence o 'incerto'", [_oa("fiscal", "do ICMS"), _oa("incerto", None)],
     ("fiscal", "do ICMS")),
    ("no empate, o pedaco COM evidencia, mesmo em 2o", [_oa("outro", None), _oa("outro", "do pedido")],
     ("outro", "do pedido")),
    ("nenhum pedaco respondeu", [dict(_BASE), dict(_BASE)], (None, None)),
])
def test_a_peca_CHUNKADA_so_da_outro_quando_nenhum_pedaco_disse_outra_coisa(caso, cards, esperado):
    """⛔ MUTANTES: tirar o par do `reduce_peca_cards` (a lista de campos dele é FECHADA); o 'outro'
    vencer o 'incerto'; o 'incerto' vencer o 'fiscal'; pegar o ÚLTIMO pedaço; tirar o desempate pela
    evidência."""
    out = reduce_peca_cards(cards)
    assert (out["objeto_da_acao"], out["objeto_da_acao_evidencia"]) == esperado, caso

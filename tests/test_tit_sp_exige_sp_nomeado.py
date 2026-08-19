# -*- coding: utf-8 -*-
"""`tit_sp` exige Sao Paulo NOMEADO, e a `uf` e ATRIBUTO com evidencia propria.

R2 do caso Ball (card 869ekv7b9, autopsia do Alfredo). ⚠️ **GUARDA FRACA POR NATUREZA,
e isso esta declarado de proposito**: a regra do item 1 e de PROMPT, e nenhum teste
unitario a executa — quem decide e a LLM. O que este arquivo trava e o que da pra
travar deterministicamente:

  · a instrucao ESTA nas DUAS prompts (o schema `PeticaoExtractCardV4` e COMPARTILHADO
    entre o ramo 1P e o 1X, entao campo/regra que chega em um chega no outro querendo
    ou nao — foi o motivo declarado do bump do 1X v1.3);
  · o `uf` do miner e um Literal FECHADO das 27 UFs, e nao `str` — e o que da constrained
    decoding e mata 'SPO'/'S.P' na ORIGEM, antes de o `varchar(2)` do banco levantar
    `StringDataRightTruncation` dentro do savepoint do sink (o `except` do laco mandaria
    a ARESTA INTEIRA pra `errors[]`, nao so a uf);
  · a prompt PROIBE derivar a uf do tribunal — o contra-desenho que o proximo leitor vai
    propor, e o que o bloco de `ADMIN_TIPO_TO_NO` (garantis-shared) derruba com numero.

⛔ O veredito REAL da regra do enum so vem da releitura, medindo a queda de claims
`tit_sp`. Piso previsto (medido 2026-08-19 sobre `telemetria.engine_llm_calls.prompt`,
150 pns com a peca retida que produziram claim `tit_sp`): o rotulo sobrevive em NO
MAXIMO 53 (35,3%) — 67 pns (44,7%) nomeiam SO outro estado.

⛔ NAO adicione aqui o cross-check `uf` do enum x `UFS_BR` do shared: este repo roda
contra o WHEEL PINADO (ver o docstring de `test_enum_contrato_sink`), e `UFS_BR` so
existe no shared novo. Ele entra no PR que BUMPA o pin, senao o gate fail-closed do
`cloudbuild-deploy.yaml` fica VERMELHO em master.
"""
from typing import get_args

import pytest

from src.agents.mov_factsheet.prompts_v4 import (
    _build_doc_incerto_prompt_v4,
    build_mov_factsheet_prompt_v4,
)
from src.agents.mov_factsheet.schemas import DocAnexado, MovInput, ProcessoContext
from src.agents.mov_factsheet.schemas_v4 import ProcessoAdminCitado

_UFS = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
    "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC",
    "SP", "SE", "TO",
}


def _enum_values(model, field: str) -> set[str]:
    pendentes = [model.model_fields[field].annotation]
    achados: set[str] = set()
    while pendentes:
        for arg in get_args(pendentes.pop()):
            achados.add(arg) if isinstance(arg, str) else pendentes.append(arg)
    return achados


@pytest.fixture
def _ctx():
    return ProcessoContext(
        cnj="0001234-56.2020.8.13.0024",
        classe="Embargos a Execucao Fiscal",
        polo_ativo="ACME COMERCIO LTDA",
        polo_passivo="ESTADO DE MINAS GERAIS",
        materia="Tributario",
    )


@pytest.fixture
def _doc():
    return DocAnexado(
        doc_key="pet-1", tipo="1", titulo="PETICAO INICIAL",
        data_documento="2022-10-03", provider="jusbrasil",
        text_content="Auto de Infracao 01.004084898-70 lavrado pela SEF/MG.",
    )


def _prompt_1p(ctx, doc):
    return build_mov_factsheet_prompt_v4(
        ctx, MovInput(mov_id="pet-1", texto=""),
        documentos_anexados=[doc], classe="peticao")


def _prompt_1x(ctx, doc):
    return _build_doc_incerto_prompt_v4(
        ctx, MovInput(mov_id="pet-1", texto=""), documentos_anexados=[doc])


@pytest.mark.parametrize("build", [_prompt_1p, _prompt_1x], ids=["1P", "1X"])
def test_tit_sp_exige_SAO_PAULO_NOMEADO_nas_DUAS_prompts(_ctx, _doc, build):
    """⛔ MUTANTE M1: arrancar a exigencia de SP do bullet de `tit_sp`.

    ⭐ A RAZAO, MEDIDA — nao foi janela de contexto, foi DESENHO DE ROTULO: a LLM leu os
    documentos INTEIROS (66.906 e 100.710 chars, "Minas Gerais" 33x e 20x, "SEF/MG" a
    ~300 caracteres do numero) e AINDA ASSIM rotulou `tit_sp`, porque `tit_sp` era o
    UNICO nome do enum para "auto de infracao estadual". A regra e o espelho literal da
    que ja disciplina `pa_estadual` ("So marque quando o texto disser o ORGAO estadual").

    ⚠️ Os DOIS ramos, porque o schema e COMPARTILHADO: regra num so deixa o outro com um
    enum que a prompt dele nao explica, sob constrained decoding."""
    p = build(_ctx, _doc)
    assert "Tribunal de Impostos e Taxas" in p
    assert "SEFAZ-SP" in p
    # e a saida de escape esta NOMEADA (senao a LLM so perde o rotulo, sem ganhar outro)
    assert "'pa_estadual'" in p and "'pa'" in p


@pytest.mark.parametrize("build", [_prompt_1p, _prompt_1x], ids=["1P", "1X"])
def test_a_uf_e_pedida_com_EVIDENCIA_e_PROIBIDA_de_derivar(_ctx, _doc, build):
    """As duas metades da regra da UF, nas duas prompts.

    ⛔ A proibicao de derivar do tribunal e a metade que o proximo leitor vai apagar
    ("mas o processo esta no TJ-SP, entao..."). Medido em prod **2026-08-19** (pelo
    segmento J.TR do CNJ): das 269 refs `tit_sp`, 142 (52,8%) estao no TJ-SP, **84
    (31,2%)** em tribunal estadual de OUTRO estado e 43 (16,0%) na Justica Federal, que
    nao diz UF nenhuma — tribunal e onde o auto e DISCUTIDO, nao de quem ele E.
    ⚠️ O bloco de `ADMIN_TIPO_TO_NO` no garantis-shared cita `127 / 98 / 41` sobre 266
    refs: e a MESMA medicao em 14/08. Tabela viva, duas datas — nao contradicao. Por
    isso as duas pontas sao DATADAS; numero sem data aqui vira contradicao aparente no
    primeiro leitor que abrir os dois arquivos juntos."""
    p = build(_ctx, _doc)
    assert "uf_evidencia" in p, "a uf foi pedida sem evidencia propria"
    assert "NUNCA derive" in p and "tribunal" in p


def test_uf_do_miner_e_LITERAL_FECHADO_das_27():
    """⛔ MUTANTE: trocar o Literal por `Optional[str]`.

    O Literal e o que da constrained decoding: 'SPO'/'S.P'/'Sao Paulo' nao chegam a
    existir. Sem ele o valor invalido viaja ate o `varchar(2)` do banco e levanta
    `StringDataRightTruncation` DENTRO do savepoint do sink — e o `except` do laco manda
    a ARESTA INTEIRA pra `errors[]`, perdendo a referencia admin, nao so a uf.
    (O writer valida de novo, com `normaliza_uf`, porque defesa em profundidade aqui e
    barata; mas a origem e este Literal.)"""
    assert _enum_values(ProcessoAdminCitado, "uf") == _UFS
    assert ProcessoAdminCitado(numero="123").uf is None          # e o default e NULO
    assert ProcessoAdminCitado(numero="123").uf_evidencia is None


def test_o_par_uf_e_uf_evidencia_e_OPCIONAL_e_nao_quebra_o_card_antigo():
    """O campo novo nao pode tornar obrigatorio o que o cache v1.5 nao tem: card antigo
    re-hidratado sem `uf` continua valido (o sink le `ad.get('uf')`)."""
    item = ProcessoAdminCitado(numero="01.004084898-70", tipo="pa_estadual",
                               contexto="lavrado pela SEF/MG")
    assert item.uf is None and item.uf_evidencia is None
    cheio = ProcessoAdminCitado(numero="01.004084898-70", tipo="pa_estadual",
                                uf="MG", uf_evidencia="lavrado pela SEF/MG")
    assert cheio.uf == "MG"

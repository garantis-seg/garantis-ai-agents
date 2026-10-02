# -*- coding: utf-8 -*-
"""O PAPEL do processo administrativo citado (card 869fay0p0, 2026-10-02).

O caso: o acórdão do CARF de outro contribuinte, citado como PRECEDENTE nas iniciais da
WestRock e da Grendene, virou membro de conexo e ponte de fusão entre as duas empresas —
o `ProcessoAdminCitado` não tinha papel. O enum é cruzado com o contrato do sink em
`test_enum_contrato_sink.py`; aqui se trava o lado do MINER:

  · o pedido ESTÁ nas DUAS prompts — o `PeticaoExtractCardV4` é COMPARTILHADO entre o 1P
    e o 1X, e campo que a prompt não explica, sob constrained decoding, é pior que campo
    ausente;
  · a regra "número de ACÓRDÃO não é número de PA" está nas duas (2 de 12 amostras
    gravaram o acórdão como PA);
  · o 1X, que lê peça DECISÓRIA, não promove PA sem ligação a `discutido`;
  · o campo é OPCIONAL, o ÚLTIMO, e sobrevive ao `model_dump` e à peça chunkada.

⚠️ Guarda FRACA por natureza, como a do valor da causa: quem decide o papel é a LLM. O
efeito (o `precedente` não vira vizinho) é provado no gather do fe-api.
"""
import pytest

from src.agents.mov_factsheet.chunking import reduce_peca_cards
from src.agents.mov_factsheet.prompts_v4 import (
    _build_doc_incerto_prompt_v4,
    build_mov_factsheet_prompt_v4,
)
from src.agents.mov_factsheet.schemas import DocAnexado, MovInput, ProcessoContext
from src.agents.mov_factsheet.schemas_v4 import PeticaoExtractCardV4, ProcessoAdminCitado


@pytest.fixture
def _ctx():
    return ProcessoContext(cnj="5010094-75.2024.4.03.6105", classe="Mandado de Seguranca Civel",
                           polo_ativo="WESTROCK", polo_passivo="UNIAO FEDERAL",
                           materia="Tributario")


@pytest.fixture
def _doc():
    return DocAnexado(doc_key="pet-1", tipo="1", titulo="PETICAO INICIAL",
                      data_documento="2024-07-29", provider="escavador",
                      text_content="Conforme o CARF, Processo Administrativo n ...")


def _prompt_1p(ctx, doc):
    return build_mov_factsheet_prompt_v4(ctx, MovInput(mov_id="pet-1", texto=""),
                                         documentos_anexados=[doc], classe="peticao")


def _prompt_1x(ctx, doc):
    return _build_doc_incerto_prompt_v4(ctx, MovInput(mov_id="pet-1", texto=""),
                                        documentos_anexados=[doc])


def _bloco_admin(p: str) -> str:
    """O trecho que instrui `processos_administrativos_citados[]`, até o próximo item de 1º
    nível. ⛔ Não procure na prompt INTEIRA: o bloco dos CNJs também tem `papel` e
    'incerto', e a guarda passava VERDE sem a instrução do admin (2 mutantes vivos, medido
    com `scripts/mutantes.py` na escrita deste teste)."""
    i = p.index("- processos_administrativos_citados[]")
    j = p.find("\n- ", i + 1)
    return p[i:j] if j != -1 else p[i:]


_RAMOS = [(_prompt_1p, "`papel` — o PAPEL deste processo administrativo NESTA ação"),
          (_prompt_1x, "`papel` — o PAPEL do PA NESTE processo")]


@pytest.mark.parametrize("build,cabecalho", _RAMOS, ids=["1P", "1X"])
def test_as_DUAS_prompts_pedem_o_papel_com_os_3_valores(_ctx, _doc, build, cabecalho):
    bloco = _bloco_admin(build(_ctx, _doc))
    assert cabecalho in bloco
    for v in ("'discutido'", "'precedente'", "'incerto'"):
        assert v in bloco, v
    # o discriminador é o PAPEL na citação (jurisprudência), não o dono
    assert "JURISPRUDÊNCIA" in bloco and "decisão de OUTRO processo" in bloco


@pytest.mark.parametrize("build", [_prompt_1p, _prompt_1x], ids=["1P", "1X"])
def test_as_DUAS_prompts_dizem_que_ACORDAO_nao_e_PA(_ctx, _doc, build):
    """2 de 12 amostras do relatório de 2026-10-01 gravaram o NÚMERO DO ACÓRDÃO como PA."""
    bloco = _bloco_admin(build(_ctx, _doc))
    assert "ACÓRDÃO" in bloco and "NNNN-NNN.NNN" in bloco
    assert "extraia só esse" in bloco


def test_o_1X_manda_o_PA_SEM_SINAL_de_peca_DECISORIA_para_INCERTO(_ctx, _doc):
    """⛔ MUTANTE (o BLOCKER da review adversarial de 02/10): herdar do CNJ "sem ligação é
    'precedente' ou 'incerto'". Lá os dois têm o MESMO efeito (nenhum vira aresta); aqui
    `precedente` SAI do gather e `incerto` FICA — a falta de sinal viraria EXCLUSÃO. A
    sentença da EF que diz "crédito constituído no PA nº X" sem dizer "da executada" seria
    tirada do conexo."""
    bloco = _bloco_admin(_prompt_1x(_ctx, _doc))
    assert ("sem ligação explícita com ESTE processo e SEM assinatura de jurisprudência é "
            "'incerto' —\n  nunca 'precedente' por falta de sinal") in bloco
    assert "'precedente' ou 'incerto'" not in bloco


@pytest.mark.parametrize("build", [_prompt_1p, _prompt_1x], ids=["1P", "1X"])
def test_precedente_SO_com_ASSINATURA_de_jurisprudencia(_ctx, _doc, build):
    """`precedente` tira o PA do conexo, então ele exige o sinal POSITIVO — a assinatura de
    jurisprudência NA citação. ⛔ "Nota de rodapé" NÃO é assinatura: a petição cita o PRÓPRIO
    PA em rodapé ("Doc. 3 – cópia do PA nº X"), e ali ele é o mais `discutido` de todos."""
    bloco = _bloco_admin(build(_ctx, _doc))
    assert "SÓ com ASSINATURA de jurisprudência" in bloco
    assert "nunca 'precedente' por falta de sinal" in bloco
    assert "rodapé" not in bloco


def test_a_description_do_schema_segue_a_MESMA_regra():
    """A description viaja no `response_schema` (constrained decoding): ela e as prompts têm
    de dizer o mesmo, senão o modelo recebe duas regras."""
    d = ProcessoAdminCitado.model_fields["papel"].description
    assert "SÓ com assinatura de jurisprudência" in d
    assert "nunca 'precedente' por falta de sinal" in d
    assert "rodapé" not in d


def test_o_papel_e_OPCIONAL_e_o_ULTIMO_campo():
    """Opcional: o card cacheado de antes do campo continua válido, e None = "não medido".
    ÚLTIMO: sob constrained decoding a ordem dos campos é a ordem da saída — os campos
    antigos saem como antes, e o papel é decidido DEPOIS do `contexto` que o audita."""
    f = ProcessoAdminCitado.model_fields["papel"]
    assert not f.is_required() and f.default is None
    assert list(ProcessoAdminCitado.model_fields) == [
        "numero", "tipo", "contexto", "uf", "uf_evidencia", "par_numero", "papel"]


def test_o_papel_SOBREVIVE_a_validacao_do_card():
    """O `_build_card_v4` valida o card com a classe e o pydantic DESCARTA extras: sem o
    campo no schema, o papel que a LLM emitisse sumiria em silêncio antes do sink."""
    card = PeticaoExtractCardV4(
        tipo_doc="peticao_inicial", resumo_ato="x", relevancia_merito="alta",
        processos_administrativos_citados=[
            {"numero": "10680.015558/2002-10", "tipo": "paf", "papel": "precedente"}],
    ).model_dump()
    assert card["processos_administrativos_citados"][0]["papel"] == "precedente"


def test_a_peca_CHUNKADA_leva_o_papel_de_cada_PA():
    """⛔ MUTANTE: o `reduce_peca_cards` remontar o item admin com lista FECHADA de campos.

    Foi assim que a peça chunkada perdeu os admin refs inteiros (medido 2026-08-05) e quase
    perdeu o valor da causa (review de 28/09). Hoje o `_union` leva o item INTEIRO; este
    teste é o que impede a próxima "limpeza" de levar só numero/tipo."""
    base = {"cdas": [], "processos_citados": [], "tipo_doc": "peticao_inicial"}
    out = reduce_peca_cards([
        {**base, "processos_administrativos_citados": [
            {"numero": "10680.015558/2002-10", "tipo": "paf", "papel": "precedente"}]},
        {**base, "processos_administrativos_citados": [
            {"numero": "16643.000337/2010-71", "tipo": "paf", "papel": "discutido"}]},
    ])
    papeis = {i["numero"]: i.get("papel") for i in out["processos_administrativos_citados"]}
    assert papeis == {"10680.015558/2002-10": "precedente", "16643.000337/2010-71": "discutido"}


@pytest.mark.parametrize("ordem", [("precedente", "discutido"), ("discutido", "precedente")])
def test_o_MESMO_numero_em_2_chunks_fica_com_o_papel_MAIS_inclusivo(ordem):
    """⛔ MUTANTE: voltar ao `_union` cru — o item do 1º chunk vence, e o papel iria junto:
    `precedente` no chunk 1 + `discutido` no chunk 2 tiraria o PA do conexo só por causa de
    onde o corte da peça caiu. É a regra do contrato (`resolve_admin_papel`), a MESMA que o
    sink aplica dentro de uma leitura; o resto do item segue o do 1º chunk."""
    base = {"cdas": [], "processos_citados": [], "tipo_doc": "peticao_inicial"}
    num = "10680.015558/2002-10"
    out = reduce_peca_cards([
        {**base, "processos_administrativos_citados": [
            {"numero": num, "tipo": "paf", "papel": ordem[0], "contexto": "chunk 1"}]},
        {**base, "processos_administrativos_citados": [
            {"numero": num, "tipo": "pa", "papel": ordem[1], "contexto": "chunk 2"}]},
    ])
    itens = out["processos_administrativos_citados"]
    assert len(itens) == 1
    assert itens[0]["papel"] == "discutido"
    assert (itens[0]["tipo"], itens[0]["contexto"]) == ("paf", "chunk 1")   # o resto: 1º chunk
    # sem claim nenhuma, o item fica como veio (papel ausente, não `None` inventado)
    sem = reduce_peca_cards([{**base, "processos_administrativos_citados": [
        {"numero": num, "tipo": "pa"}]}, dict(base)])
    assert "papel" not in sem["processos_administrativos_citados"][0]

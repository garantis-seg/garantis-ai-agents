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


def test_o_1X_nao_promove_PA_de_peca_DECISORIA_a_discutido(_ctx, _doc):
    """Decisão e sentença citam acórdão do CARF o tempo todo — o mesmo cuidado do `papel`
    dos CNJs no ramo 1X."""
    assert ("em peça DECISÓRIA, PA citado sem ligação\n  explícita com a parte é "
            "'precedente' ou 'incerto' — nunca 'discutido'") in _prompt_1x(_ctx, _doc)


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

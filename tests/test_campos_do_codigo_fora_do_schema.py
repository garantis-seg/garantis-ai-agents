"""O campo que o codigo sobrescreve sempre fica FORA do response_schema do LLM.

O LLM pagava token de saida por campos que o materializer do garantis-shared descarta: os
valores do merito, a agregacao da probabilidade de exito e a trajetoria (L3), e a
probabilidade de exito do processo (L2). O teste cruza os 2 lados do contrato: o campo saiu
do schema daqui E o materializer do shared ainda o grava no card. Sem o 2o lado, o teste
ficaria verde com o campo sumido do card persistido.
"""
from __future__ import annotations

import ast
import importlib.util
import pathlib

from src.agents.merito_synthesis.schemas import MeritoSynthesisCard, ProbabilidadeExitoMerito
from src.agents.processo_synthesis.schemas import ProcessoSynthesisCard, ProcessoSynthesisCardRich

#: Campos do card L3 que o materializer do shared grava depois da chamada do LLM.
_L3_DO_CODIGO = {
    "valor_em_disputa_melhor_evidencia",
    "valor_garantia_melhor_evidencia",
    "probabilidade_exito_merito",
    "trajetoria",
    "trajetoria_motivo",
}


def _chaves_que_o_materializer_l3_grava() -> set[str]:
    """As chaves `card["x"] = ...` do materializer L3 do garantis-shared, lidas do FONTE."""
    spec = importlib.util.find_spec("garantis_shared.engine_v6.layer3_merito_synthesis.materializer")
    assert spec and spec.origin, "o materializer L3 do garantis-shared nao foi achado"
    arvore = ast.parse(pathlib.Path(spec.origin).read_text(encoding="utf-8"))
    chaves = set()
    for no in ast.walk(arvore):
        if not isinstance(no, ast.Assign):
            continue
        for alvo in no.targets:
            if (isinstance(alvo, ast.Subscript) and isinstance(alvo.value, ast.Name)
                    and alvo.value.id == "card" and isinstance(alvo.slice, ast.Constant)):
                chaves.add(alvo.slice.value)
    return chaves


def test_l3_os_campos_do_codigo_nao_estao_no_schema_do_llm():
    campos = set(MeritoSynthesisCard.model_fields)
    assert not (_L3_DO_CODIGO - {"probabilidade_exito_merito"}) & campos
    # Da probabilidade de exito, o LLM emite so a frase. A agregacao e do codigo.
    assert set(ProbabilidadeExitoMerito.model_fields) == {"contribuicao_no_risco"}
    # Controle: o que o LLM decide continua no schema.
    assert {"risco", "justificativa", "probabilidade_exito_merito"} <= campos


def test_l3_o_materializer_do_shared_grava_cada_campo_que_saiu_do_schema():
    gravadas = _chaves_que_o_materializer_l3_grava()
    assert _L3_DO_CODIGO <= gravadas, sorted(_L3_DO_CODIGO - gravadas)
    # Controle: o leitor acha as chaves que o redator de prosa grava.
    assert {"justificativa", "narrativa_executiva"} <= gravadas


def test_l2_a_probabilidade_de_exito_saiu_do_schema_e_o_card_servido_a_mantem_vazia():
    assert "probabilidade_exito" not in ProcessoSynthesisCard.model_fields
    servido = ProcessoSynthesisCardRich(processo_numero="0").model_dump()
    assert servido["probabilidade_exito"] == {
        "classificacao": None, "score": None, "criterios_aplicados": [], "justificativa": None,
    }
    # Mesmo que o LLM o emita, o card servido sai vazio.
    emitido = ProcessoSynthesisCard(
        processo_numero="0", probabilidade_exito={"classificacao": "provavel"},
    ).model_dump()
    assert ProcessoSynthesisCardRich(**emitido).model_dump()["probabilidade_exito"]["classificacao"] is None

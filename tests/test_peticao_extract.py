# -*- coding: utf-8 -*-
"""Esqueleto do ramo PETIÇÃO INICIAL (peticao_extract.v1) — FASE 4 conexos.

Invariantes do esqueleto: dispatch por classe='peticao' (opt-in; prod nunca envia),
schema superset (card v4 + cdas/processos_citados), versão POR RAMO, e render com
contexto afirmativo + regras de extração dirigida do contrato
(prompts/fase4-alfredo-handoff-peticao-extraction.md). O prompt jurídico (regras de
`papel`) é DS do Alfredo — estes testes travam a estrutura, não o wording.
"""
import pytest

from src.agents.mov_factsheet.prompts_v4 import build_mov_factsheet_prompt_v4
from src.agents.mov_factsheet.schemas import DocAnexado, MovInput, ProcessoContext
from src.agents.mov_factsheet.schemas_v4 import (
    MovFactSheetCardV4,
    PETICAO_PROMPT_VERSION,
    PeticaoExtractCardV4,
)


@pytest.fixture
def processo():
    return ProcessoContext(
        cnj="0001234-56.2020.8.26.0053",
        classe="Embargos à Execução Fiscal",
        polo_ativo="ACME COMERCIO LTDA",
        polo_passivo="ESTADO DE SAO PAULO",
        materia="Tributário",
    )


@pytest.fixture
def doc_peticao():
    return DocAnexado(
        doc_key="pet-1", tipo="1", titulo="PETICAO INICIAL - PETICAO INICIAL",
        data_documento="2022-10-03", provider="jusbrasil",
        text_content=(
            "EXCELENTISSIMO SENHOR DOUTOR JUIZ. ACME COMERCIO LTDA vem opor EMBARGOS "
            "A EXECUCAO FISCAL, distribuidos por dependencia aos autos da Execucao "
            "Fiscal n 0009999-11.2019.8.26.0053, alegando nulidade da CDA 12.345.678-9 "
            "(ICMS, R$ 1.000.000,00)..."
        ),
    )


def test_render_peticao(processo, doc_peticao):
    mov = MovInput(mov_id="pet-1", texto="")
    prompt = build_mov_factsheet_prompt_v4(
        processo, mov, documentos_anexados=[doc_peticao], classe="peticao",
    )
    # contexto afirmativo + extração dirigida
    assert "É a PETIÇÃO INICIAL" in prompt
    assert "cdas[]" in prompt
    assert "processos_citados[]" in prompt
    assert "'originario'" in prompt           # regra de ouro do papel
    assert "'jurisprudencia'" in prompt
    assert "PeticaoExtractCardV4" in prompt   # schema do ramo
    # herda o contexto neutro + vocab da família
    assert "CONTEXTO DO PROCESSO" in prompt
    assert "CONTEXTO FISCAL/TRIBUTÁRIO" in prompt
    # metadata do doc renderizada
    assert "titulo: PETICAO INICIAL - PETICAO INICIAL" in prompt
    assert "fonte: jusbrasil" in prompt
    # nada dos blocos que não pertencem ao ramo
    assert "MOV ANTERIOR" not in prompt
    assert "RESUMO DO PROCESSO" not in prompt
    assert "DOCUMENTO AVULSO" not in prompt


def test_schema_superset_nao_dropa_conectores():
    """Validar com a classe do ramo preserva cdas/processos_citados; a base dropa
    (pydantic ignora extras) — por isso o agent passa card_cls no ramo peticao."""
    parsed = {
        "resumo_ato": "Embargos opostos contra a EF, alegando nulidade da CDA.",
        "tipo_doc": "peticao_inicial",
        "relevancia_merito": "alta",
        "cdas": [{"numero": "12.345.678-9", "ente": "estadual", "tributo": "ICMS",
                  "valor_total": 1000000.0}],
        "processos_citados": [{"cnj": "0009999-11.2019.8.26.0053", "papel": "originario",
                               "contexto": "distribuidos por dependencia aos autos da..."}],
        "confianca_extracao": 0.9,
    }
    card = PeticaoExtractCardV4(**parsed)
    assert card.cdas[0].numero == "12.345.678-9"
    assert card.processos_citados[0].papel == "originario"
    # a base (mov_factsheet) descartaria os conectores — comportamento documentado
    base = MovFactSheetCardV4(**parsed)
    assert not hasattr(base, "cdas")


def test_versao_por_ramo():
    assert PETICAO_PROMPT_VERSION.startswith("peticao_extract.v1")
    from src.agents.mov_factsheet.schemas_v4 import PROMPT_VERSION_V4
    assert PROMPT_VERSION_V4 != PETICAO_PROMPT_VERSION


def test_ramos_existentes_inalterados(processo):
    """classe None/1D continuam nos ramos atuais — peticao é opt-in puro."""
    mov = MovInput(mov_id="m1", data="2026-01-01", texto="Vistos. Despacho de expediente.")
    p_mov = build_mov_factsheet_prompt_v4(processo, mov)
    assert "É a PETIÇÃO INICIAL" not in p_mov
    assert "=== MOVIMENTAÇÃO ===" in p_mov
    doc = DocAnexado(doc_key="d1", text_content="contrato social anexo " * 20)
    p_doc = build_mov_factsheet_prompt_v4(processo, mov, documentos_anexados=[doc], classe="1D")
    assert "É a PETIÇÃO INICIAL" not in p_doc
    assert "DOCUMENTO AVULSO" in p_doc


def test_versoes_de_prompt_vem_do_CONTRATO_compartilhado_nao_de_literal_local():
    """🚨 As 2 versões são lidas por TRÊS processos (agent carimba, materializer
    persiste, `_CURRENT_PETICAO_VERSIONS` do fe-api decide quem é stale) e o fe-api
    NÃO importa este repo. Enquanto foram literal duplicado, o bump de 2026-08-07
    não chegou no terceiro e INVERTEU o filtro de stale: 896 cards já atuais
    re-extraídos e 1.039 velhos nunca refrescados (medido em prod 2026-08-12).

    ⛔ Não compare com literal re-digitado aqui — seria a mesma duplicação que o
    teste existe pra impedir, com nome de teste. A asserção é de IDENTIDADE de
    origem: o símbolo TEM que vir do contrato no garantis-shared."""
    from garantis_shared.engine_v6.persistence import peticao_contract as contrato

    from src.agents.mov_factsheet import schemas_v4

    assert schemas_v4.PETICAO_PROMPT_VERSION is contrato.PETICAO_PROMPT_VERSION
    assert schemas_v4.DOC_INCERTO_PROMPT_VERSION is contrato.DOC_INCERTO_PROMPT_VERSION

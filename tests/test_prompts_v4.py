# -*- coding: utf-8 -*-
"""Invariantes de render do prompt v4 (mov_factsheet).

Lote 1/1.3 do prompt-review (2026-06-10): o caminho v4 NÃO renderiza o bloco
MOV ANTERIOR — prod roda paralelo sempre (sequential_l1=False), então o bloco
nunca aparecia; a remoção é limpeza sem mudança de comportamento. Estes testes
travam o invariante (e o shape geral do render) sem chamar LLM.
"""
import pytest

from src.agents.mov_factsheet.prompts_v4 import build_mov_factsheet_prompt_v4
from src.agents.mov_factsheet.schemas import (
    DocAnexado,
    FallbackContext,
    MovInput,
    ProcessoContext,
)


@pytest.fixture
def processo():
    return ProcessoContext(
        cnj="0001234-56.2020.8.26.0053",
        classe="Execução Fiscal",
        polo_ativo="ESTADO DE SAO PAULO",
        polo_passivo="ACME COMERCIO LTDA",
        materia="Tributário",
    )


@pytest.fixture
def mov():
    return MovInput(
        mov_id="cluster-abc",
        data="2026-02-02",
        tipo="Decisao",
        texto="Vistos. O agravante interpos agravo de instrumento.",
    )


def test_mov_anterior_nunca_renderiza_no_v4(processo, mov):
    """Mesmo com fallback_context inteiro preenchido, o v4 não renderiza MOV
    ANTERIOR (1.3) nem RESUMO DO PROCESSO (decisão D, v4.2)."""
    fb = FallbackContext(
        processo_resumo_ia="Execucao fiscal de ICMS contra ACME.",
        mov_anterior_resumo="Juizo recusou a apolice por valor insuficiente.",
        mov_anterior_categoria="decisao_interlocutoria",
        distance_dias_mov_anterior=12,
    )
    prompt = build_mov_factsheet_prompt_v4(processo, mov, fallback_context=fb)
    assert "MOV ANTERIOR" not in prompt
    assert "PREVALECE" not in prompt
    # v4.2 (decisão D): RESUMO DO PROCESSO também não renderiza mais.
    assert "RESUMO DO PROCESSO" not in prompt
    assert "Execucao fiscal de ICMS contra ACME." not in prompt


def test_render_prod_shape_1a(processo, mov):
    """Shape prod (paralelo): mov sem doc, fallback só com resumo."""
    fb = FallbackContext(processo_resumo_ia="Resumo do processo aqui.")
    prompt = build_mov_factsheet_prompt_v4(processo, mov, fallback_context=fb)
    assert "MOV ANTERIOR" not in prompt
    assert "RESUMO DO PROCESSO" not in prompt
    assert "=== MOVIMENTAÇÃO ===" in prompt
    assert "Sem doc anexo" in prompt           # instrução do ramo sem-doc
    assert "CONTEXTO FISCAL/TRIBUTÁRIO" in prompt  # família fiscal via matéria


def test_render_1b_com_doc(processo, mov):
    doc = DocAnexado(doc_key="d1", tipo="decisao", text_content="DECIDO: nego provimento.")
    prompt = build_mov_factsheet_prompt_v4(processo, mov, documentos_anexados=[doc])
    assert "DOCUMENTOS ANEXADOS A ESTA MOV (1 doc(s))" in prompt
    assert "MOV ANTERIOR" not in prompt
    assert "nem a mov anterior" not in prompt  # instrução não referencia bloco inexistente


def test_render_documento_1d(processo, mov):
    """Ramo DOCUMENTO (ex-órfão) v4.3: ganha vocab de família, regras crus e a
    metadata do doc no render (censo 2026-06-11: metadata jusbrasil 100% preenchida)."""
    doc = DocAnexado(
        doc_key="d1", tipo="1", titulo="PETICAO INICIAL - PETICAO INICIAL",
        data_documento="2022-10-03", provider="jusbrasil",
        text_content="EXCELENTISSIMO SENHOR DOUTOR JUIZ. ACME vem opor embargos...",
    )
    prompt = build_mov_factsheet_prompt_v4(processo, mov, documentos_anexados=[doc], classe="1D")
    assert "DOCUMENTO AVULSO" in prompt
    assert "DOCUMENTO ÓRFÃO" not in prompt
    assert "CONTEXTO FISCAL/TRIBUTÁRIO" in prompt          # vocab da família agora entra
    assert "REGRAS DOS CAMPOS CRUS" in prompt              # regras crus agora entram
    assert "titulo: PETICAO INICIAL - PETICAO INICIAL" in prompt  # metadata renderizada
    assert "fonte: jusbrasil" in prompt
    assert "MOV ANTERIOR" not in prompt
    assert "RESUMO DO PROCESSO" not in prompt


# ── v4.4 sem-limite (decisão "qualidade > custo", 2026-06-11) ──

def test_v44_todos_os_docs_renderizam_sem_cap(processo, mov):
    """Sem cap de 5 docs/mov e sem cap de 8k/doc: 7 docs de 30k entram inteiros."""
    docs = [DocAnexado(doc_key=str(i), text_content=f"DOC{i} " + "y" * 30_000) for i in range(7)]
    prompt = build_mov_factsheet_prompt_v4(processo, mov, documentos_anexados=docs)
    assert "DOC 7/7" in prompt
    assert "omitidos" not in prompt
    assert "TRUNCADO" not in prompt


def test_v44_orcamento_por_unidade(processo, mov):
    """Orçamento agregado (2M chars): doc que estoura é truncado com marcador; o
    excedente vira marcador explícito de omissão (no silent caps).

    titulo='SENTENCA' => perfil 'peça' (lê completo) — senão o perfil de leitura
    (2026-06-19) marcaria doc grande SEM título legal como evidência (head+tail)
    e cada doc consumiria ~80k em vez de 900k, fazendo todos caberem."""
    big = [DocAnexado(doc_key=str(i), titulo="SENTENCA", text_content="z" * 900_000) for i in range(4)]
    prompt = build_mov_factsheet_prompt_v4(processo, mov, documentos_anexados=big)
    assert "DOC 3/4" in prompt and "DOC 4/4" not in prompt
    assert "[TRUNCADO a 200000 chars do original]" in prompt
    assert "[+ 1 docs omitidos — orçamento de janela do modelo]" in prompt


def test_v44_mov_texto_sem_cap_de_3k(processo):
    mov_longa = MovInput(mov_id="m-longa", texto="t" * 50_000)
    prompt = build_mov_factsheet_prompt_v4(processo, mov_longa)
    assert "t" * 49_000 in prompt

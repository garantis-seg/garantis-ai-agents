# -*- coding: utf-8 -*-
"""Truth-table do roteamento de família do vocab v4 (_familia_key).

Origem: censo do prompt-review 2026-06-10 achou Execução Fiscal roteada pro vocab
TRABALHISTA quando a classe vem como tree-path CNJ ("1116 - PROCESSO CÍVEL E DO
TRABALHO -> ... -> Execução Fiscal") — o cabeçalho contém 'TRABALHO' pra qualquer
classe. Fix: com '->' na classe, só o último segmento entra no match.
"""
import pytest

from src.agents.mov_factsheet.prompts_v4 import _familia_key


@pytest.mark.parametrize(
    "materia,classe,esperado",
    [
        # casos planos (comportamento pré-existente, não pode mudar)
        (None, "Execução Fiscal", "fiscal"),
        ("Tributário", "Agravo de Instrumento", "fiscal"),
        ("Trabalhista", None, "trabalhista"),
        (None, "Reclamação Trabalhista", "trabalhista"),
        (None, "Procedimento Comum Cível", "civel"),
        (None, None, "civel"),
        ("Civel", "Apelação", "civel"),
        # tree-path CNJ — o bug do censo (proc 5159436-51.2025.8.09.0051/TJGO)
        (None, "1116 - PROCESSO CÍVEL E DO TRABALHO -> Processo de Execução -> Execução Fiscal", "fiscal"),
        ("Tributário", "1116 - PROCESSO CÍVEL E DO TRABALHO -> Processo de Execução -> Execução Fiscal", "fiscal"),
        # tree-path de classe genuinamente trabalhista segue trabalhista
        (None, "985 - PROCESSO DO TRABALHO -> Rito Ordinário -> Reclamação Trabalhista", "trabalhista"),
        # tree-path cível NÃO pode mais cair em trabalhista pelo header
        (None, "7 - PROCESSO CÍVEL E DO TRABALHO -> Processo de Conhecimento -> Procedimento Comum Cível", "civel"),
        # matéria continua mandando mesmo com tree-path genérico
        ("Trabalhista", "7 - PROCESSO CÍVEL E DO TRABALHO -> Processo de Conhecimento -> Procedimento Comum", "trabalhista"),
    ],
)
def test_familia_key(materia, classe, esperado):
    assert _familia_key({"materia": materia, "classe": classe}) == esperado


# ── delegação pra garantis_shared.materia (card 869edc6u7, 2026-08-25) ────────
# A truth-table acima é o CONTROLE: ela passa igual antes e depois. O que segue é
# o que a delegação corrige, e cada caso saiu de uma medição na base viva.

def test_o_separador_tambem_pode_ser_hifen():
    """O guard antigo só cortava o cabeçalho da árvore CNJ quando o separador era
    '->'. Com ' - ' (formato de '1208 - PROCESSO CÍVEL E DO TRABALHO - ...') ele
    passava batido e o processo tributário ia pro vocab trabalhista. 203 pns."""
    assert _familia_key({
        "materia": None, "assunto": "ICMS/ Imposto sobre Circulação de Mercadorias",
        "classe": "1208 - PROCESSO CÍVEL E DO TRABALHO - RECURSOS - AGRAVO INTERNO",
    }) == "fiscal"


def test_o_assunto_do_processo_agora_e_visto():
    """`assunto` não era declarado no ProcessoContext e pydantic o descartava — o
    L1 escolhia a família sem nunca ver o assunto. 204 pns viravam civel."""
    assert _familia_key({
        "materia": None, "classe": "MANDADO DE SEGURANCA VARA CIVEL",
        "assunto": "Cofins, Contribuições Sociais, Contribuições",
    }) == "fiscal"


def test_segmento_do_cnj_pega_o_que_o_texto_nao_diz():
    """classe 'AR' + assunto 'Ação Rescisória' não tem palavra trabalhista nenhuma."""
    assert _familia_key({
        "cnj": "1000588-96.2022.5.00.0000", "assunto": "Ação Rescisória", "classe": "AR",
    }) == "trabalhista"


def test_familia_pronta_do_shared_vence_o_fallback_local():
    """O caminho normal: o shared resolve (ele tem banco) e manda pronto."""
    assert _familia_key({
        "familia": "fiscal", "materia": "Trabalhista", "classe": "Reclamação Trabalhista",
    }) == "fiscal"
    # valor fora do vocabulário é ignorado, não propagado pro VOCAB_FAMILIA
    assert _familia_key({"familia": "tributario", "classe": "Execução Fiscal"}) == "fiscal"


def test_fallback_local_NAO_toca_o_banco():
    """⛔ garantis-ai-agents roda com `uses_cloud_sql: false`. Se o fallback passasse
    `classe_cnj_code`, o degrau da curadoria leria ref.cnj_classes e levantaria —
    derrubando TODO prompt do L1."""
    import garantis_shared.cnj_classify_ref as ref

    def _boom():
        raise AssertionError("_familia_key tocou o banco")

    orig, ref._load = ref._load, _boom
    ref.invalidate_cache()
    try:
        assert _familia_key({
            "cnj": "0023083-62.2019.4.01.3800", "classe_cnj_code": 1116,
            "classe": "Execução Fiscal", "assunto": None, "materia": None,
        }) == "fiscal"
    finally:
        ref._load = orig
        ref.invalidate_cache()

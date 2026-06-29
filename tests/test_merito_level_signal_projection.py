"""extracao-sinais-merito-level (2026-06-29): projecoes determinisitcas dos sinais
merito-level — gate de precisao do L2 (motivo_extincao so em extinto) + propagacao L2->L3
(echo + suspensao) que fecha o 'satisfacao=0/86'."""
from __future__ import annotations

from src.agents.processo_synthesis.agent import _project_decisao_facts
from src.agents.merito_synthesis.agent import (
    _norm_pn,
    _project_merito_decisao_facts,
)


# ── L2: gate de precisao do motivo_extincao ──

def _mov(mov_id, data, natureza, motivo=None, tem=True):
    return {
        "mov_id": mov_id, "data": data,
        "decisao": {"tem_decisao": tem, "natureza": natureza, "motivo_extincao": motivo},
    }


def test_l2_gate_keeps_motivo_when_vigente_is_extinto():
    card = {"decisao_vigente": {"natureza": "extinto_sem_merito", "sentido": "desfavoravel"}}
    movs = [_mov("m1", "2026-01-30", "extinto_sem_merito", "satisfacao")]
    _project_decisao_facts(card, movs)
    assert card["decisao_vigente"]["motivo_extincao"] == "satisfacao"


def test_l2_gate_nulls_motivo_when_vigente_not_extinto():
    # card procedente, mas o unico mov decidido carrega satisfacao (fallback _vigente_mov):
    # sem o gate, motivo vazava pro card procedente (FP medido ~50% no satisfacao).
    card = {"decisao_vigente": {"natureza": "procedente", "sentido": "favoravel"}}
    movs = [_mov("m1", "2025-06-11", "extinto_sem_merito", "satisfacao")]
    _project_decisao_facts(card, movs)
    assert card["decisao_vigente"].get("motivo_extincao") is None


def test_l2_no_decided_mov_is_noop():
    card = {"decisao_vigente": {"natureza": "procedente"}}
    _project_decisao_facts(card, [_mov("m1", "2025-01-01", None, tem=False)])
    # nada a projetar — decisao_vigente intacto (sem KeyError)
    assert card["decisao_vigente"]["natureza"] == "procedente"


# ── L3: propagacao do processo governante pro decisao_atual ──

def test_norm_pn_strips_formatting():
    assert _norm_pn("0005526-70.2021.8.19.0045") == _norm_pn("00055267020218190045")
    assert _norm_pn(None) == ""


def test_l3_projects_echo_and_suspensao_from_origem():
    card = {"decisao_atual": {"processo_de_origem": "1001107-39.2016.5.02.0481",
                              "natureza": "improcedente", "sentido": "desfavoravel"}}
    ps = [
        {"processo_numero": "10011073920165020481",
         "decisao_vigente": {"natureza": "improcedente",
                             "motivo_extincao": None,
                             "efeito_suspensivo": None,
                             "instrumento_cautelar": "nenhum",
                             "suspensao_processual": "irdr_tema_repetitivo",
                             "suspensao_vigente": True,
                             "suspensao_data": "2023-04-18"}},
        {"processo_numero": "99999999999999999999",
         "decisao_vigente": {"suspensao_processual": "parcelamento_transacao"}},
    ]
    _project_merito_decisao_facts(card, ps)
    da = card["decisao_atual"]
    assert da["suspensao_processual"] == "irdr_tema_repetitivo"  # do processo de origem
    assert da["suspensao_vigente"] is True
    assert da["suspensao_data"] == "2023-04-18"
    assert da["instrumento_cautelar"] == "nenhum"


def test_l3_satisfacao_propagates_to_merito_level():
    # o caso central do 'satisfacao=0/86': o sinal existe no L2 e DEVE chegar no decisao_atual.
    card = {"decisao_atual": {"processo_de_origem": "00100438020185150047",
                              "natureza": "extinto_sem_merito"}}
    ps = [{"processo_numero": "00100438020185150047",
           "decisao_vigente": {"natureza": "extinto_sem_merito", "motivo_extincao": "satisfacao"}}]
    _project_merito_decisao_facts(card, ps)
    assert card["decisao_atual"]["motivo_extincao"] == "satisfacao"


def test_l3_no_match_leaves_decisao_atual_unchanged():
    card = {"decisao_atual": {"processo_de_origem": "00000000000000000000", "natureza": "improcedente"}}
    ps = [{"processo_numero": "11111111111111111111",
           "decisao_vigente": {"suspensao_processual": "irdr_tema_repetitivo"}}]
    _project_merito_decisao_facts(card, ps)
    assert "suspensao_processual" not in card["decisao_atual"] or \
        card["decisao_atual"].get("suspensao_processual") is None


def test_l3_error_card_is_noop():
    card = {"error": "boom"}
    _project_merito_decisao_facts(card, [])
    assert card == {"error": "boom"}

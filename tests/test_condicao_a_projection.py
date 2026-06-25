"""Condição A determinística (2026-06-25): projeção code-side dos fatos ECHO do L1.

Guarda os 2 invariantes do design aprovado pela mãe:
1. ZERO-DRIFT: o response_schema do LLM (ProcessoSynthesisCard.decisao_vigente) continua
   DecisaoVigente v2.3 INTOCADA — o LLM nunca vê os campos echo (emiti-los rebaixava o
   risco_factual; medido no canário, é o SCHEMA não só o prompt).
2. PROJEÇÃO CORRETA: os 3 fatos vêm do mov L1 vigente (matching: mais recente tem_decisao
   com natureza == card.natureza; fallback = mais recente tem_decisao). Alvo: m473
   (extinto_sem_merito + satisfacao).
"""
from __future__ import annotations

from src.agents.processo_synthesis.agent import _project_decisao_facts, _vigente_mov
from src.agents.processo_synthesis.schemas import (
    DecisaoVigente,
    DecisaoVigenteRich,
    MovFactSheetMin,
    ProcessoSynthesisCard,
)


def _mov(mov_id, data, *, tem_decisao=True, natureza=None, motivo_extincao=None,
         instrumento_cautelar=None, efeito_suspensivo=None) -> MovFactSheetMin:
    return MovFactSheetMin(mov_id=mov_id, data=data, decisao={
        "tem_decisao": tem_decisao, "natureza": natureza,
        "motivo_extincao": motivo_extincao, "instrumento_cautelar": instrumento_cautelar,
        "efeito_suspensivo": efeito_suspensivo,
    })


# ── Invariante 1: zero-drift (LLM schema pristino) ──────────────────────────
def test_llm_response_schema_decisaovigente_is_v23():
    """O card que vira response_schema do Gemini usa DecisaoVigente v2.3, NÃO a Rich."""
    assert ProcessoSynthesisCard.model_fields["decisao_vigente"].annotation is DecisaoVigente


def test_decisaovigente_llm_model_has_no_echo_fields():
    """Byte-identico: DecisaoVigente (response do LLM) não pode ter os campos echo."""
    for f in ("motivo_extincao", "instrumento_cautelar", "efeito_suspensivo"):
        assert f not in DecisaoVigente.model_fields
    # a Rich (persistida, code-side) TEM os 3
    for f in ("motivo_extincao", "instrumento_cautelar", "efeito_suspensivo"):
        assert f in DecisaoVigenteRich.model_fields


# ── Invariante 2: matching + projeção ───────────────────────────────────────
def test_vigente_mov_picks_latest_matching_natureza():
    movs = [
        _mov("a", "2022-01-01", natureza="improcedente"),
        _mov("b", "2023-06-01", natureza="extinto_sem_merito", motivo_extincao="satisfacao"),
        _mov("c", "2024-01-01", natureza="interlocutoria"),  # mais recente mas natureza != card
    ]
    v = _vigente_mov(movs, "extinto_sem_merito")
    assert v.mov_id == "b"


def test_vigente_mov_fallback_latest_decided():
    movs = [_mov("a", "2022-01-01", natureza="improcedente"),
            _mov("b", "2024-01-01", natureza="procedente")]
    v = _vigente_mov(movs, "homologatoria")  # nenhum casa -> fallback mais recente
    assert v.mov_id == "b"


def test_vigente_mov_none_when_no_decision():
    movs = [_mov("a", "2022-01-01", tem_decisao=False)]
    assert _vigente_mov(movs, "improcedente") is None


def test_project_m473_satisfacao():
    """m473: decisao_vigente extinto_sem_merito + mov L1 satisfacao -> projeta satisfacao."""
    card = {"decisao_vigente": {"natureza": "extinto_sem_merito", "sentido": "favoravel"}}
    movs = [_mov("x", "2022-05-01", natureza="extinto_sem_merito", motivo_extincao="satisfacao",
                 efeito_suspensivo=True)]
    _project_decisao_facts(card, movs)
    assert card["decisao_vigente"]["motivo_extincao"] == "satisfacao"
    assert card["decisao_vigente"]["efeito_suspensivo"] is True
    # campos v2.3 preservados
    assert card["decisao_vigente"]["sentido"] == "favoravel"


def test_project_terminativa_not_satisfacao():
    card = {"decisao_vigente": {"natureza": "extinto_sem_merito"}}
    movs = [_mov("x", "2022-05-01", natureza="extinto_sem_merito", motivo_extincao="terminativa")]
    _project_decisao_facts(card, movs)
    assert card["decisao_vigente"]["motivo_extincao"] == "terminativa"


def test_project_nonextincao_motivo_none():
    """Decisão vigente não-extinção -> motivo_extincao projetado como None (campo presente)."""
    card = {"decisao_vigente": {"natureza": "improcedente"}}
    movs = [_mov("x", "2023-01-01", natureza="improcedente")]
    _project_decisao_facts(card, movs)
    assert card["decisao_vigente"]["motivo_extincao"] is None


def test_project_noop_when_no_decided_mov():
    card = {"decisao_vigente": {"natureza": "improcedente"}}
    before = dict(card["decisao_vigente"])
    _project_decisao_facts(card, [_mov("x", "2023-01-01", tem_decisao=False)])
    assert card["decisao_vigente"] == before  # inalterado


def test_project_never_raises_on_garbage():
    _project_decisao_facts({"error": "x"}, [])          # no-op
    _project_decisao_facts({}, None)                     # no-op
    _project_decisao_facts({"decisao_vigente": None}, [])  # no-op

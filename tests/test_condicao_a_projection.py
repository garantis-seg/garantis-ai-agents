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
         instrumento_cautelar=None, efeito_suspensivo=None,
         transito_certificado=False) -> MovFactSheetMin:
    return MovFactSheetMin(mov_id=mov_id, data=data, decisao={
        "tem_decisao": tem_decisao, "natureza": natureza,
        "motivo_extincao": motivo_extincao, "instrumento_cautelar": instrumento_cautelar,
        "efeito_suspensivo": efeito_suspensivo,
        "transito_certificado": transito_certificado,
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


def test_http_response_preserves_echo_fields_AND_base_strips():
    """O BUG (verificacao adversarial da mae): a rota re-serializava por ProcessoSynthesisCard
    BASE (decisao_vigente = DecisaoVigente, extra='ignore') -> os 3 campos echo sumiam no JSON.
    Fix: ProcessoSynthesisResponse.card = ProcessoSynthesisCardRich. Round-trip que faltava (o
    report validou o dict in-process, NAO a resposta serializada)."""
    from src.agents.processo_synthesis.schemas import (
        ProcessoSynthesisCard, ProcessoSynthesisCardRich, ProcessoSynthesisResponse,
    )
    card_data = {"processo_numero": "123", "decisao_vigente": {
        "natureza": "extinto_sem_merito", "motivo_extincao": "satisfacao",
        "instrumento_cautelar": "suspensao_exigibilidade_ctn", "efeito_suspensivo": True}}
    # FIX: via ProcessoSynthesisResponse (o que a rota retorna) os 3 SOBREVIVEM
    dv = ProcessoSynthesisResponse(
        card=ProcessoSynthesisCardRich(**card_data)
    ).model_dump()["card"]["decisao_vigente"]
    assert dv["motivo_extincao"] == "satisfacao"
    assert dv["instrumento_cautelar"] == "suspensao_exigibilidade_ctn"
    assert dv["efeito_suspensivo"] is True
    # REGRESSAO-GUARD: o card BASE ainda stripa (prova que o tipo Rich e necessario)
    assert "motivo_extincao" not in ProcessoSynthesisCard(**card_data).model_dump()["decisao_vigente"]


def test_projection_does_not_mutate_risk_or_other_fields():
    """Negativo (dim 4): a projecao SO toca decisao_vigente — risco_factual/jurisprudencial/
    estado/prob_exito ficam intactos. Guarda a direcao under-rating contra refactor."""
    import copy
    card = {"risco_factual": "Alto", "risco_jurisprudencial": "Medio",
            "risco_processo_intermediario": "Alto", "estado_processual": "execucao em curso",
            "probabilidade_exito": {"classificacao": "possivel"},
            "decisao_vigente": {"natureza": "extinto_sem_merito"}}
    snapshot = copy.deepcopy({k: v for k, v in card.items() if k != "decisao_vigente"})
    _project_decisao_facts(card, [_mov("x", "2022-01-01", natureza="extinto_sem_merito",
                                       motivo_extincao="terminativa")])
    assert {k: v for k, v in card.items() if k != "decisao_vigente"} == snapshot  # risco intacto
    assert card["decisao_vigente"]["motivo_extincao"] == "terminativa"


def test_project_never_raises_on_garbage():
    _project_decisao_facts({"error": "x"}, [])          # no-op
    _project_decisao_facts({}, None)                     # no-op
    _project_decisao_facts({"decisao_vigente": None}, [])  # no-op


# ── L0 DADO (2026-06-28): a projecao NAO deriva/override transito ─────────────
# Decisao de design (provada por A/B LLM): a distincao merito-vs-execucao e text-only
# -> uma correcao deterministica de transito quebra o trap Acao Rescisoria (movs de
# execucao tem natureza de merito). Logo a projecao deixa transito_certificado COMO O
# LLM emitiu; o fix vive no PROMPT v2.4. Guarda contra reintroduzir o override fragil.


def test_projection_leaves_transito_as_llm_emitted():
    """A projecao copia os 3 echo facts mas NAO toca transito_certificado — fica o valor
    do LLM (corrigido pelo prompt v2.4), tanto pra true quanto pra false."""
    for transito in (True, False):
        card = {"processo_numero": "p", "decisao_vigente": {
            "natureza": "improcedente", "transito_certificado": transito}}
        # ate com uma "re-adjudicacao" depois, transito permanece como veio do LLM
        movs = [_mov("t", "2022-11-23", natureza="improcedente", transito_certificado=True),
                _mov("exec", "2023-05-31", natureza="procedente")]  # excecao pre-exec (execucao)
        _project_decisao_facts(card, movs)
        assert card["decisao_vigente"]["transito_certificado"] is transito


def test_route_http_roundtrip_preserves_echo(monkeypatch):
    """⭐ O teste que FALTAVA (o bug escapou por isto): HTTP de verdade pela rota com o agent
    mockado — os 3 campos echo têm que estar na resposta JSON. Sem isto, o strip volta silencioso."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import src.api.routes.processo_synthesis as route_mod

    async def _fake_classify(*a, **k):
        return {"card": {"processo_numero": "1", "decisao_vigente": {
                    "natureza": "extinto_sem_merito", "motivo_extincao": "satisfacao",
                    "instrumento_cautelar": "suspensao_exigibilidade_ctn", "efeito_suspensivo": True}},
                "raw_response": {}, "llm_raw_prompt": {},
                "prompt_version": "processo_synthesis.v2.3", "usage": {}}

    monkeypatch.setattr(route_mod, "classify_processo_synthesis", _fake_classify)
    app = FastAPI(); app.include_router(route_mod.router)
    r = TestClient(app).post("/processo-synthesis/classify",
                             json={"processo_numero": "1", "tipo_judicial": "fiscal", "mov_factsheets": []})
    assert r.status_code == 200
    dv = r.json()["card"]["decisao_vigente"]
    assert dv["motivo_extincao"] == "satisfacao"
    assert dv["instrumento_cautelar"] == "suspensao_exigibilidade_ctn"
    assert dv["efeito_suspensivo"] is True

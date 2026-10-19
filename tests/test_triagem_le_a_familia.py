"""A triagem do L1 escolhe o bloco de familia pela familia do payload, a MESMA que escolhe o
vocabulario do L1 v4 — nunca pelo texto da linha `Materia` (o `resolve_materia` do shared, com
a apolice na frente). Pelo texto, o bloco curado so chegava a quem tem a planilha da apolice,
e o resto recebia `FAMILIA: <texto livre>`.

Run: pytest tests/test_triagem_le_a_familia.py -q
"""
import pytest

from src.agents.mov_factsheet.prompts_v4 import VOCAB_FAMILIA, build_mov_factsheet_prompt_v4
from src.agents.mov_triage.prompts import build_mov_triage_prompt
from src.agents.mov_triage.schemas import MovInput, ProcessoContext

_MOV = MovInput(mov_id="m1", texto="Juntada de peticao.")
# O inicio de cada bloco curado da triagem, por familia do payload.
_BLOCO = {
    "fiscal": "MATERIA (ramo do direito): TRIBUTARIO/FISCAL.",
    "trabalhista": "MATERIA (ramo do direito): TRABALHISTA.",
    "civel": "MATERIA (ramo do direito): CIVEL (generica).",
}


def _proc(**kw):
    return ProcessoContext(cnj="00000000000000000000", **kw)


@pytest.mark.parametrize("familia", ["fiscal", "trabalhista", "civel"])
@pytest.mark.parametrize("materia", ["Dívida Ativa", "Trabalhista", "Cível", None])
def test_a_familia_do_payload_escolhe_o_bloco_e_o_texto_da_materia_nao(familia, materia):
    prompt = build_mov_triage_prompt(_proc(materia=materia, familia=familia), _MOV)
    assert _BLOCO[familia] in prompt
    assert [b for f, b in _BLOCO.items() if f != familia and b in prompt] == []
    assert "FAMILIA:" not in prompt and "NAO INFORMADA" not in prompt


@pytest.mark.parametrize("familia", ["fiscal", "trabalhista", "civel"])
def test_a_triagem_e_o_l1_v4_leem_a_mesma_familia(familia):
    proc = _proc(materia="Execução Fiscal", familia=familia)
    assert _BLOCO[familia] in build_mov_triage_prompt(proc, _MOV)
    assert VOCAB_FAMILIA[familia] in build_mov_factsheet_prompt_v4(proc, _MOV)


def test_payload_sem_familia_cai_no_mesmo_fallback_do_l1(caplog):
    """Sem a `familia` no payload, as 2 leituras caem no fallback DB-less do L1 v4, que
    conta a queda (FALLBACK_DISPAROU): a triagem nao tem fallback proprio."""
    proc = _proc(materia="Tributário")
    with caplog.at_level("WARNING"):
        prompt = build_mov_triage_prompt(proc, _MOV)
    assert _BLOCO["fiscal"] in prompt
    assert "FALLBACK_DISPAROU familia=materia_familia_sem_payload" in caplog.text

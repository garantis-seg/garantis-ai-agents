"""Testes do L3 v2.5 SEM CAP no render (decisao Elton 2026-06-12) + limpeza
stale juris (intro nao promete mais payload que nao chega desde v2.2)."""
from __future__ import annotations

from src.agents.merito_synthesis.prompts import (
    PROMPT_VERSION_BASE,
    _summarize_processo_synthesis,
    build_merito_synthesis_prompt,
)
from src.agents.merito_synthesis.schemas import (
    MeritoSynthesisRequest,
    ProcessoSynthesisMin,
)


def test_version_bumped():
    assert PROMPT_VERSION_BASE == "merito_synthesis.v2.7.3"


def test_lifecycle_completo_sem_cap_de_5():
    ps = ProcessoSynthesisMin(
        processo_numero="0000000-00.0000.0.00.0000",
        tipo_judicial="fiscal",
        lifecycle_garantia=[
            {"data": f"2024-0{(i % 9) + 1}-01", "evento": "apresentacao",
             "tipo_garantia": "seguro_garantia", "status_pos": f"st{i}"}
            for i in range(8)
        ],
    )
    block = _summarize_processo_synthesis(ps)
    assert "Lifecycle garantia (8 eventos):" in block
    assert all(f"st{i}" in block for i in range(8))  # antes cortava em 5


def test_criterios_completos_e_justificativa_sem_truncagem():
    longa = "j" * 500
    ps = ProcessoSynthesisMin(
        processo_numero="0000000-00.0000.0.00.0000",
        tipo_judicial="fiscal",
        probabilidade_exito={
            "classificacao": "possivel", "score": 0.7,
            "justificativa": longa,
            "criterios_aplicados": [f"criterio numero {i} " + "c" * 200 for i in range(4)],
        },
    )
    block = _summarize_processo_synthesis(ps)
    assert longa in block                                   # antes [:140]
    assert all(f"criterio numero {i}" in block for i in range(4))  # antes [:2]
    assert "c" * 200 in block                               # antes [:160]


# v2.7.3 (2026-07-02): test_decisao_anterior_json_integro DELETADO — o bloco
# SNAPSHOT ANTERIOR saiu do prompt (anti-ancora + seed estavel); a invariancia
# do prompt a previous_snapshot e testada em test_gemini_determinism.py.


def test_intro_nao_promete_jurisprudencia():
    req = MeritoSynthesisRequest(
        merito_id=1,
        processo_syntheses=[
            ProcessoSynthesisMin(
                processo_numero="0000000-00.0000.0.00.0000", tipo_judicial="fiscal",
            )
        ],
    )
    p = build_merito_synthesis_prompt(req)
    assert "+ jurisprudencia da tese + snapshot anterior" not in p
    assert "NAO vem\nneste payload" in p

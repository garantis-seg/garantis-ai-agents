"""L2 PROSA — passe de redacao. Testa as partes DETERMINISTICAS (sem LLM):
o prompt (risco fixo + filtro + sem blocos de decisao), o fallback template
(sempre limpo + coerente com risco_final) e os helpers do guard.
"""
import pytest

from src.agents.merito_synthesis.prose_lint import lint
from src.agents.merito_synthesis.prompts import build_redacao_prompt
from src.agents.merito_synthesis.redacao import (
    _corrective_block,
    _dominant_decisao,
    _ensure_complete,
    _facts2cell,
    _template_prose,
)
from src.agents.merito_synthesis.schemas import RedacaoRequest


def _req(risco="Medio", procs=None):
    return RedacaoRequest(
        merito_id=1, risco_final=risco, razao_social="ACME LTDA",
        cnpj_principal="12345678000190",
        processo_syntheses=procs or [{
            "processo_numero": "0001234-56.2020.8.26.0100",
            "decisao_vigente": {"sentido": "desfavoravel", "instancia": "1g",
                                "recorrida": True, "transito_certificado": False},
        }],
    )


# ── Prompt ─────────────────────────────────────────────────────────────────


def test_prompt_fixes_risco_and_keeps_filter():
    p = build_redacao_prompt(_req(risco="Alto"))
    assert "risco = Alto" in p
    assert "<filtro_redacao_advogado>" in p          # filtro reusado VERBATIM
    assert p.rstrip().endswith("</filtro_redacao_advogado>")  # ultimo (recency)


def test_prompt_does_not_redecide():
    """O passe NAO re-decide: nada de matriz/escala/protocolo/consistency check."""
    p = build_redacao_prompt(_req())
    assert "ESCALA EXPLICITA" not in p
    assert "CONSISTENCY CHECK" not in p
    assert "PROTOCOLO" not in p
    assert "NAO e classificar nem recalcular" in p


def test_prompt_carries_facts():
    p = build_redacao_prompt(_req())
    assert "ACME LTDA" in p
    assert "0001234-56.2020.8.26.0100" in p


# ── Template fallback (guaranteed clean) ───────────────────────────────────


@pytest.mark.parametrize("risco", ["Baixo", "Medio", "Alto", "Altissimo"])
def test_template_always_clean_and_consistent(risco):
    card = _template_prose(_req(risco=risco))
    # nenhum campo de prosa vaza List-B
    for f in ("justificativa", "narrativa_executiva", "contribuicao_no_risco",
              "decisao_justificativa_breve"):
        assert lint(card[f]) == [], (risco, f, card[f])
    for pp in card["proximos_passos_provaveis"]:
        assert lint(pp) == []
    # a prosa nomeia o nivel decidido (coerencia por construcao)
    assert f"Risco {risco}." in card["narrativa_executiva"]
    assert card["proximos_passos_provaveis"]


def test_template_narrates_transito_desfavoravel():
    procs = [{"processo_numero": "0009999-00.2019.8.26.0100",
              "decisao_vigente": {"sentido": "desfavoravel", "transito_certificado": True}}]
    card = _template_prose(_req(risco="Altissimo", procs=procs))
    assert "transitada em julgado" in card["justificativa"]
    assert "0009999-00.2019.8.26.0100" in card["justificativa"]


# ── Guard helpers ──────────────────────────────────────────────────────────


def test_facts2cell_ordering():
    assert _facts2cell({"sentido": "desfavoravel", "transito_certificado": True}) == "Altissimo"
    assert _facts2cell({"sentido": "favoravel", "natureza": "procedente"}) == "Baixo"
    assert _facts2cell({"natureza": "extinto_sem_merito"}) == "Baixo"
    assert _facts2cell({"sentido": "parcial", "natureza": "parcialmente_procedente"}) == "Medio"
    # natureza=None curto-circuita pra Baixo (sem decisao de merito = baixo),
    # espelhando eval_29.facts2cell verbatim — mesmo com sentido setado.
    assert _facts2cell({"sentido": "parcial"}) == "Baixo"


def test_dominant_picks_worst_band():
    procs = [
        {"processo_numero": "AAA", "decisao_vigente": {"sentido": "favoravel"}},
        {"processo_numero": "BBB", "decisao_vigente": {"sentido": "desfavoravel", "transito_certificado": True}},
    ]
    dv, pn = _dominant_decisao(_req(procs=procs))
    assert pn == "BBB"


def test_ensure_complete_fills_empty_main_fields():
    """LLM deixou campos vazios/None -> template (limpo) preenche; peca_pivo None->''."""
    card = {"justificativa": "", "narrativa_executiva": None, "contribuicao_no_risco": "  ",
            "decisao_justificativa_breve": None, "peca_pivo_motivo": None,
            "proximos_passos_provaveis": []}
    out = _ensure_complete(card, _req(risco="Alto"))
    for f in ("justificativa", "narrativa_executiva", "contribuicao_no_risco",
              "decisao_justificativa_breve"):
        assert out[f] and out[f].strip(), f
        assert lint(out[f]) == []
    assert out["proximos_passos_provaveis"]
    assert out["peca_pivo_motivo"] == ""  # sem peca clara -> string vazia, nunca None


def test_ensure_complete_keeps_nonempty_llm_prose():
    """Nao clobbera prosa boa do LLM."""
    card = {"justificativa": "Texto bom do LLM citando CNJ.",
            "narrativa_executiva": "Resumo. Risco Alto.",
            "contribuicao_no_risco": "Baixa perspectiva de exito.",
            "decisao_justificativa_breve": "Decisao desfavoravel mantida.",
            "peca_pivo_motivo": "A sentenca define o estado.",
            "proximos_passos_provaveis": ["Acompanhar."]}
    out = _ensure_complete(dict(card), _req(risco="Alto"))
    for k, v in card.items():
        assert out[k] == v


def test_corrective_block_echoes_leaks():
    block = _corrective_block([("decimal_score", "0.20"), ("literal_bastidor", "Daycoval")])
    assert "0.20" in block
    assert "Daycoval" in block
    assert "Lista B" in block

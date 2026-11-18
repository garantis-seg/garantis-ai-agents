"""Depois das rodadas de correção, o qualificador anula só o campo rejeitado (17/11/2026).

Loop de fichas, rodada 5: 2 conexos ficaram sem qualificação nenhuma por 1 campo do estado
processual. O campo ruim sai null, e o resto da resposta fica.
"""
import copy

from src.agents.qualificador_conexo.agent import _anular_campos_rejeitados as anular

_EP = "processos[1].estado_processual"


def _parsed() -> dict:
    return {"processos": [
        {"numero": "A", "estado_processual": {"origem": {"tipo": "auto_de_infracao", "prova": {"x": 1}}}},
        {"numero": "B", "estado_processual": {
            "origem": {"tipo": "auto_de_infracao", "data": "2020-01-01", "prova": {"x": 1}},
            "decisoes": [{"etapa": "DRJ", "data": "2021-01-01"}, {"etapa": "CARF", "data": "2024-01-01"}],
            "admissibilidade": {"resultado": "nao_admitido", "data": "2025-01-01"},
            "cabe_agravo": False, "via_esgotada": True, "esgotada_em": None,
            "documentos_lidos": ["d1", "d2", "d3"]}},
    ], "garantias": []}


def _erro(campo: str, valor=None) -> dict:
    return {"campo": campo, "erro": "x", "valor_anterior": valor}


def test_a_via_esgotada_sem_data_fica_desconhecida_e_o_resto_fica():
    antes = _parsed()
    novo = anular(antes, [_erro(f"{_EP}.esgotada_em")])
    ep = novo["processos"][1]["estado_processual"]
    assert ep["via_esgotada"] is None and ep["esgotada_em"] is None
    assert ep["decisoes"] == antes["processos"][1]["estado_processual"]["decisoes"]
    assert ep["admissibilidade"] and ep["cabe_agravo"] is False
    assert novo["processos"][0] == antes["processos"][0]
    assert antes["processos"][1]["estado_processual"]["via_esgotada"] is True, "a entrada não muda"


def test_o_cabe_agravo_rejeitado_fica_null():
    ep = anular(_parsed(), [_erro(f"{_EP}.cabe_agravo", False)])["processos"][1]["estado_processual"]
    assert ep["cabe_agravo"] is None and ep["admissibilidade"]["resultado"] == "nao_admitido"


def test_a_origem_rejeitada_guarda_a_data():
    novo = anular(_parsed(), [_erro(f"{_EP}.origem.prova.trecho"), _erro("processos[0].estado_processual.origem")])
    assert novo["processos"][1]["estado_processual"]["origem"] == {"tipo": None, "data": "2020-01-01", "prova": None}
    assert novo["processos"][0]["estado_processual"]["origem"] == {"tipo": None, "prova": None}


def test_varios_campos_do_mesmo_processo_saem_juntos():
    novo = anular(_parsed(), [_erro(f"{_EP}.origem.prova.trecho"), _erro(f"{_EP}.cabe_agravo", False),
                              _erro(f"{_EP}.esgotada_em")])
    ep = novo["processos"][1]["estado_processual"]
    assert ep["origem"]["tipo"] is None and ep["cabe_agravo"] is None and ep["via_esgotada"] is None


def test_o_erro_fora_do_estado_processual_mantem_o_422():
    for campo in ("processos[1].prova", "garantias[0].estado", "$", f"{_EP}.confianca",
                  f"{_EP}.decisoes[0].prova", f"{_EP}.admissibilidade.prova", f"{_EP}.documentos_lidos"):
        assert anular(_parsed(), [_erro(campo)]) is None, campo
    assert anular(_parsed(), [_erro(f"{_EP}.cabe_agravo"), _erro("garantias[0].estado")]) is None
    assert anular(_parsed(), []) is None and anular(None, [_erro(f"{_EP}.cabe_agravo")]) is None
    assert anular(copy.deepcopy(_parsed()), [_erro("processos[9].estado_processual.cabe_agravo")]) is None


# ── Ponta a ponta: o conexo sai qualificado, sem o campo rejeitado ───────────────────

def test_ponta_a_ponta_a_via_esgotada_sem_data_nao_derruba_a_qualificacao(monkeypatch):
    """Rodada 5 do loop: `via_esgotada=true exige esgotada_em` deu 422 e a ficha saiu sem
    qualificação nenhuma. Agora o campo sai null, e as decisões provadas ficam."""
    from tests import test_qualificador_conexo as t

    ruim = t._emissao_carf(t._estado_irb(esgotada_em=None))
    prov = t._ProvAuditorSustenta(t._leituras_carf(), [ruim])
    r = t._rodar(prov, monkeypatch, req=t._request_carf())
    ep = r.processos[0].estado_processual
    assert ep.via_esgotada is None and ep.esgotada_em is None
    assert ep.decisoes, "as decisões provadas ficam"
    assert r.rodadas_de_correcao == 2, "o modelo teve as 2 rodadas antes de o código anular"


def test_ponta_a_ponta_o_cabe_agravo_sem_admissibilidade_sai_null(monkeypatch):
    from tests import test_qualificador_conexo as t

    ruim = t._emissao_carf(t._estado_irb(admissibilidade=None, cabe_agravo=False, via_esgotada=None,
                                         esgotada_em=None))
    prov = t._ProvAuditorSustenta(t._leituras_carf(), [ruim])
    r = t._rodar(prov, monkeypatch, req=t._request_carf())
    assert r.processos[0].estado_processual.cabe_agravo is None

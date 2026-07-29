"""ApoliceContextMin achata lifecycle/vigencia aninhados do card kind='apolice'.

Bug de contrato medido em 2026-07-29: o writer canonico
(garantis_shared.engine_v6.cards.apolice.build_apolice_card) aninha o ciclo de vida em
summary['lifecycle'] e a validade em summary['vigencia'], mas o schema lia
`apresentada`/`aceita` no TOPO com extra='ignore' -> ambos None em 0/125.788 cards
ativos de prod, e o prompt nunca renderizava ACEITA/RECUSADA/VENCIDA.

Os payloads abaixo sao o SHAPE REAL do card (copiado de build_apolice_card), nao um
shape inventado — e o que garante que o achatamento casa com o writer.
"""
from src.agents.processo_synthesis.prompts import _summarize_apolice
from src.agents.processo_synthesis.schemas import ApoliceContextMin


def _card(**over):
    """Shape exato de build_apolice_card (summary)."""
    card = {
        "apolice_id": 775,
        "numero_apolice": "017412020000107750005814",
        "seguradora": "DAYCOVAL SEGUROS S.A.",
        "valor_is": 83592696.0,
        "vigencia": {"inicio": "2023-08-07", "termino": "2028-08-06",
                     "farol": "verde", "dias_para_vencimento": 738},
        "is_central_for_merito": True,
        "central_source": None,
        "lifecycle": {"apresentada": True, "presented_at": "2023-09-01",
                      "acceptance_status": "aceita", "acceptance_decision_at": "2023-10-02",
                      "acceptance_reason": None, "dias_em_pendencia": None},
        "recusa_em_conexos": [],
    }
    card.update(over)
    return card


def test_lifecycle_aninhado_vira_campo_do_topo():
    ap = ApoliceContextMin(**_card())
    assert ap.apresentada is True
    assert ap.aceita is True
    assert ap.vigencia_farol == "verde"
    assert ap.vigencia_termino == "2028-08-06"


def test_recusada_vira_aceita_false():
    lc = _card()["lifecycle"] | {"acceptance_status": "recusada"}
    ap = ApoliceContextMin(**_card(lifecycle=lc))
    assert ap.aceita is False, "recusada tem que virar False, nao None (None esconde a recusa)"


def test_sem_decisao_fica_none_nao_false():
    """offered/sem court_presentation: apresentada mas SEM decisao. False diria 'RECUSADA'."""
    lc = {"apresentada": True, "acceptance_status": None}
    ap = ApoliceContextMin(**_card(lifecycle=lc))
    assert ap.apresentada is True
    assert ap.aceita is None


def test_caller_antigo_com_campos_achatados_segue_funcionando():
    ap = ApoliceContextMin(numero_apolice="X", seguradora="Y", apresentada=True, aceita=False)
    assert (ap.apresentada, ap.aceita) == (True, False)
    assert ap.vigencia_farol is None


def test_topo_explicito_ganha_do_aninhado():
    ap = ApoliceContextMin(**_card(aceita=False))
    assert ap.aceita is False


def test_card_sem_lifecycle_nem_vigencia_nao_quebra():
    ap = ApoliceContextMin(numero_apolice="X")
    assert (ap.apresentada, ap.aceita, ap.vigencia_farol) == (None, None, None)


def test_prompt_renderiza_aceita_e_vigencia():
    linha = _summarize_apolice(ApoliceContextMin(**_card()))
    assert "ACEITA" in linha
    assert "apresentada" in linha
    assert "vigente ate 2028-08-06" in linha
    assert "central no merito" in linha


def test_prompt_marca_vencida():
    """farol VERMELHO = termination_date < CURRENT_DATE na view = EXPIRADA (nao 'vencendo').
    65% do LMG que entraria pelo cohort novo e apolice vencida — o L2 precisa ver isso."""
    v = {"inicio": "2019-01-01", "termino": "2021-03-04", "farol": "vermelho",
         "dias_para_vencimento": -1972}
    linha = _summarize_apolice(ApoliceContextMin(**_card(vigencia=v)))
    assert "VENCIDA em 2021-03-04" in linha
    assert "vigente ate" not in linha


def test_prompt_omite_vigencia_indeterminada():
    """CINZA (cancelada ou sem data) -> 'indeterminado': nao inventa fato de vigencia."""
    v = {"inicio": None, "termino": None, "farol": "indeterminado", "dias_para_vencimento": None}
    linha = _summarize_apolice(ApoliceContextMin(**_card(vigencia=v)))
    assert "VENCIDA" not in linha and "vigente" not in linha


def test_regressao_do_bug_o_shape_real_nao_chega_mais_vazio():
    """O bug exato: com o card REAL, apresentada/aceita chegavam None e a linha do prompt
    saia sem nenhum sinal de ciclo de vida."""
    linha = _summarize_apolice(ApoliceContextMin(**_card()))
    assert linha != "Apolice 017412020000107750005814 (DAYCOVAL SEGUROS S.A.) | IS=R$ 83.592.696 | (central no merito)"

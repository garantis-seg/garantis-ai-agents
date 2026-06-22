# -*- coding: utf-8 -*-
"""Chunk map-reduce de processo gigante no L2 (2026-06-22) — split + reduce."""
from src.agents.processo_synthesis.chunking import (
    L2_CHUNK_CHARS,
    reduce_processo_synthesis_cards,
    split_movs_chronological,
)
from src.agents.processo_synthesis.schemas import (
    MovFactSheetMin,
    ProcessoSynthesisCard,
    ProcessoSynthesisRequest,
)


def _mov(i, resumo="x", data="2020-01-01"):
    # data constante → sort por (data, mov_id) = ordem de mov_id (insertion order)
    return MovFactSheetMin(mov_id=f"mov{i:05d}", data=data, resumo_ato=resumo)


def _req(movs):
    return ProcessoSynthesisRequest(
        processo_numero="123", tipo_judicial="fiscal", mov_factsheets=movs,
    )


# ── split_movs_chronological ───────────────────────────────────────────────

def test_split_none_para_pequeno():
    assert split_movs_chronological(_req([_mov(i, "curto") for i in range(10)])) is None


def test_split_lotes_por_tamanho_cobre_tudo_e_ordena():
    big = "a" * 4000
    req = _req([_mov(i, big) for i in range(40)])   # ~160k render > 120k budget
    variants = split_movs_chronological(req)
    assert variants and len(variants) >= 2
    # cobre TODAS as movs (sem perder/duplicar)
    flat = [f.mov_id for v in variants for f in v.mov_factsheets]
    assert len(flat) == 40 and len(set(flat)) == 40
    # ordem cronológica (data, mov_id) preservada na concatenação dos lotes
    assert flat == sorted(flat)
    # cada lote respeita o teto de 200 movs
    assert all(len(v.mov_factsheets) <= 200 for v in variants)


def test_split_respeita_teto_200_movs():
    # 600 movs pequenas (~245 render cada) ~147k > budget → chunka; teto 200/lote binda 1º
    req = _req([_mov(i, "y" * 220) for i in range(600)])
    variants = split_movs_chronological(req)
    assert variants
    assert all(len(v.mov_factsheets) <= 200 for v in variants)
    assert sum(len(v.mov_factsheets) for v in variants) == 600


def test_split_um_mov_gigante_sozinho_none():
    # 1 mov estoura o budget sozinho — chunkar não ajuda (só daria 1 lote)
    assert split_movs_chronological(_req([_mov(0, "z" * 500_000)])) is None


def test_split_budget_override():
    req = _req([_mov(i, "k" * 100) for i in range(20)])
    assert split_movs_chronological(req) is None             # sob 120k default
    assert split_movs_chronological(req, budget=500) is not None  # budget minúsculo → chunka


def test_split_chunk_chars_default():
    assert L2_CHUNK_CHARS == 120_000


# ── reduce_processo_synthesis_cards ────────────────────────────────────────

def _card(**over):
    base = {
        "processo_numero": "123", "tipo_judicial": "fiscal",
        "estado_processual": "", "decisao_vigente": {}, "lifecycle_garantia": [],
        "risco_processo_intermediario": "Baixo", "risco_factual": "Indeterminado",
        "risco_jurisprudencial": "Indeterminado", "trajetoria_dentro_processo": "indefinida",
        "peca_pivo_candidata": {}, "valor_em_disputa": None, "valor_garantia": None,
        "probabilidade_exito": {}, "movs_processed": 0, "confianca": 0.7,
        "evidence_artifacts": [],
    }
    base.update(over)
    return base


def test_reduce_decisao_hierarquia_nao_ultimo_lote():
    # transito num lote ANTIGO vence interlocutória num lote RECENTE (REGRA F / load-bearing)
    c0 = _card(decisao_vigente={
        "natureza": "improcedente", "instancia": "1g",
        "transito_certificado": True, "data": "2022-01-01",
    })
    c1 = _card(decisao_vigente={
        "natureza": "interlocutoria", "instancia": "1g", "data": "2024-06-01",
    })
    out = reduce_processo_synthesis_cards([c0, c1])
    assert out["decisao_vigente"]["natureza"] == "improcedente"
    assert out["decisao_vigente"]["transito_certificado"] is True


def test_reduce_decisao_instancia_superior_vence():
    c0 = _card(decisao_vigente={"natureza": "improcedente", "instancia": "1g", "data": "2021-01-01"})
    c1 = _card(decisao_vigente={"natureza": "procedente", "instancia": "2g", "data": "2020-01-01"})
    out = reduce_processo_synthesis_cards([c0, c1])
    assert out["decisao_vigente"]["instancia"] == "2g"  # 2g > 1g mesmo sendo mais antiga


def test_reduce_risco_from_anchor_nao_max():
    # risco vem do lote da DECISÃO (anchor); um risco numa janela SEM decisão não sobrepõe.
    anchor = _card(
        decisao_vigente={"natureza": "improcedente", "instancia": "1g", "data": "2022-01-01"},
        risco_processo_intermediario="Alto", risco_factual="Alto",
    )
    recent_no_decision = _card(risco_processo_intermediario="Baixo", risco_factual="Baixo")
    out = reduce_processo_synthesis_cards([anchor, recent_no_decision])
    assert out["risco_processo_intermediario"] == "Alto"   # do anchor
    assert out["risco_factual"] == "Alto"


def test_reduce_risco_de_escalation_acordo_nao_over_flag():
    # §F1: sentença improcedente (Alto) antiga; acordo homologado (Baixo) recente. O acordo
    # homologatório é decisão de mérito mais RECENTE → vira o anchor → risco Baixo.
    # (MAX cego daria Alto = over-flag da de-escalação real.)
    old = _card(
        decisao_vigente={"natureza": "improcedente", "instancia": "1g", "data": "2020-01-01"},
        risco_processo_intermediario="Alto", risco_factual="Alto",
    )
    acordo = _card(
        decisao_vigente={"natureza": "homologatoria", "instancia": "1g", "data": "2023-06-01"},
        risco_processo_intermediario="Baixo", risco_factual="Baixo",
    )
    out = reduce_processo_synthesis_cards([old, acordo])
    assert out["risco_processo_intermediario"] == "Baixo"
    assert out["decisao_vigente"]["natureza"] == "homologatoria"


def test_reduce_risco_indeterminado_quando_nenhum_concreto():
    # sem decisão em lote nenhum → anchor = último lote → risco dele
    out = reduce_processo_synthesis_cards([
        _card(risco_factual="Indeterminado"), _card(risco_factual="Indeterminado"),
    ])
    assert out["risco_factual"] == "Indeterminado"


def test_reduce_transito_or_merge_de_outra_janela():
    # §F3: certidão de trânsito cai num lote POSTERIOR sem a sentença (natureza=null → fora
    # do anchor); o flag transito tem que sobreviver via OR-merge, senão sub-flaga o pior caso.
    sentenca = _card(decisao_vigente={
        "natureza": "improcedente", "instancia": "1g", "data": "2021-01-01",
        "transito_certificado": False,
    })
    certidao = _card(decisao_vigente={
        "natureza": None, "sentido": None, "transito_certificado": True,
    })
    out = reduce_processo_synthesis_cards([sentenca, certidao])
    assert out["decisao_vigente"]["natureza"] == "improcedente"     # anchor = a sentença
    assert out["decisao_vigente"]["transito_certificado"] is True   # mergeado da outra janela


def test_reduce_union_valores_sum_estado():
    c0 = _card(
        estado_processual="estado antigo",
        lifecycle_garantia=[{"data": "2020-01-01", "mov_id": "m1", "evento": "apresentacao"}],
        valor_em_disputa=100.0, valor_garantia=50.0, movs_processed=200, confianca=0.9,
    )
    c1 = _card(
        estado_processual="estado RECENTE",
        lifecycle_garantia=[
            {"data": "2020-01-01", "mov_id": "m1", "evento": "apresentacao"},  # duplicata
            {"data": "2021-05-01", "mov_id": "m2", "evento": "aceitacao"},
        ],
        valor_em_disputa=300.0, valor_garantia=None, movs_processed=180, confianca=0.6,
    )
    out = reduce_processo_synthesis_cards([c0, c1])
    assert out["estado_processual"] == "estado RECENTE"     # último lote
    assert len(out["lifecycle_garantia"]) == 2             # union dedup
    assert out["valor_em_disputa"] == 300.0                # max
    assert out["valor_garantia"] == 50.0                   # max não-null
    assert out["movs_processed"] == 380                    # soma (total real lido)
    assert out["confianca"] == 0.6                         # min (janelas parciais)


def test_reduce_prob_exito_from_anchor_nao_ultimo():
    # §F2: prob_exito vem do lote da DECISÃO (anchor), não do tail procedural recente fraco.
    anchor = _card(
        decisao_vigente={"natureza": "improcedente", "instancia": "1g", "data": "2022-01-01"},
        probabilidade_exito={"classificacao": "possivel", "score": 0.7},
    )
    tail = _card(probabilidade_exito={"classificacao": "poucas_chances", "score": 0.4})
    out = reduce_processo_synthesis_cards([anchor, tail])
    assert out["probabilidade_exito"]["classificacao"] == "possivel"  # do anchor, não do tail


def test_reduce_card_valida_no_schema():
    # o dict reduzido tem que re-instanciar no ProcessoSynthesisCard (a route faz isso)
    out = reduce_processo_synthesis_cards([
        _card(decisao_vigente={"natureza": "improcedente", "instancia": "1g"}, risco_factual="Alto"),
        _card(estado_processual="x"),
    ])
    card = ProcessoSynthesisCard(**out)
    assert card.processo_numero == "123"
    assert card.risco_factual == "Alto"   # do anchor (c0, com a decisão)

# -*- coding: utf-8 -*-
"""Chunk map-reduce de peça grande no L1 (2026-06-19) — split + reduce."""
from src.agents.mov_factsheet.chunking import (
    CHUNK_SIZE,
    _split_text,
    reduce_peca_cards,
    split_large_peca_variants,
    sum_usage,
)
from src.agents.mov_factsheet.schemas import DocAnexado


def _doc(titulo="", text="", tipo=None):
    return DocAnexado(doc_key="k", titulo=titulo, tipo=tipo, text_content=text)


# ── split ──

def test_split_text_cobre_tudo_e_respeita_size():
    text = ("linha de texto aqui\n" * 30_000)  # ~600k
    pieces = _split_text(text, size=180_000)
    assert "".join(pieces) == text          # nada perdido
    assert all(len(p) <= 180_000 for p in pieces)
    assert len(pieces) >= 3


def test_split_variants_none_para_pequeno_ou_evidencia():
    assert split_large_peca_variants([_doc(titulo="PETICAO", text="x" * 50_000)]) is None  # pequeno
    # doc grande SEM título legal = evidência (head+tail no prompt builder, não chunk)
    assert split_large_peca_variants([_doc(titulo="DEMONSTRATIVO", text="x" * 600_000)]) is None


def test_split_variants_peca_grande():
    docs = [_doc(titulo="PETICAO INICIAL", text="a\n" * 200_000),  # ~400k peça
            _doc(titulo="DESPACHO", text="curto")]
    variants = split_large_peca_variants(docs)
    assert variants and len(variants) >= 2
    for j, v in enumerate(variants):
        assert len(v) == 2                       # preserva o outro doc
        assert v[1].text_content == "curto"
        assert f"PARTE {j + 1}/" in v[0].text_content  # marcador de parte


# ── reduce ──

def _card(**kw):
    base = {"mov_id": "m1", "resumo_ato": "", "tipo_doc": "outros",
            "relevancia_merito": "baixa",
            "decisao": {"tem_decisao": False, "natureza": None, "transito_certificado": False},
            "evento_garantia": {"tipo": "nenhum"},
            "valores": {"valor_debito_executado": None, "valor_garantia": None}}
    base.update(kw)
    return base


def test_reduce_pega_decisao_do_chunk_com_sinal():
    cards = [
        _card(resumo_ato="parte 1 fatos", relevancia_merito="baixa"),
        _card(resumo_ato="parte 2 dispositivo", relevancia_merito="alta",
              tipo_doc="sentenca",
              decisao={"tem_decisao": True, "natureza": "procedente", "transito_certificado": False}),
    ]
    out = reduce_peca_cards(cards)
    assert out["relevancia_merito"] == "alta"           # max
    assert out["tipo_doc"] == "sentenca"                # do mais relevante (não 'outros')
    assert out["decisao"]["natureza"] == "procedente"   # chunk com sinal vence
    assert "parte 1 fatos" in out["resumo_ato"] and "parte 2 dispositivo" in out["resumo_ato"]


def test_reduce_evento_e_valores():
    cards = [
        _card(valores={"valor_debito_executado": 1000.0, "valor_garantia": None}),
        _card(evento_garantia={"tipo": "acionamento"},
              valores={"valor_debito_executado": 5000.0, "valor_garantia": 200.0}),
    ]
    out = reduce_peca_cards(cards)
    assert out["evento_garantia"]["tipo"] == "acionamento"
    assert out["valores"]["valor_debito_executado"] == 5000.0   # max não-null
    assert out["valores"]["valor_garantia"] == 200.0


def test_reduce_union_cdas_citados():
    cards = [
        _card(cdas=[{"numero": "111"}], processos_citados=[{"cnj": "AAA"}]),
        _card(cdas=[{"numero": "111"}, {"numero": "222"}], processos_citados=[{"cnj": "BBB"}]),
    ]
    out = reduce_peca_cards(cards)
    assert {c["numero"] for c in out["cdas"]} == {"111", "222"}   # dedup
    assert {p["cnj"] for p in out["processos_citados"]} == {"AAA", "BBB"}


def test_reduce_ignora_resumo_ruido():
    cards = [_card(resumo_ato="lixo", relevancia_merito="ruido"),
             _card(resumo_ato="conteudo bom", relevancia_merito="media")]
    out = reduce_peca_cards(cards)
    assert out["resumo_ato"] == "conteudo bom"


def test_sum_usage():
    out = sum_usage([
        {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15, "cost_usd": 0.1, "model": "g"},
        {"input_tokens": 20, "output_tokens": 7, "total_tokens": 27, "cost_usd": 0.2},
    ])
    assert out["input_tokens"] == 30 and out["output_tokens"] == 12 and out["total_tokens"] == 42
    assert abs(out["cost_usd"] - 0.3) < 1e-9
    assert out["model"] == "g"

"""Test determinismo do L2 processo_synthesis prompt builder (Bug 3 handoff).

Cascade c0f906be (Alto) vs 5455d1d0 (Baixo) m=3: prompts L2 divergiram em
16.4% (334 spans) dominantemente em #<mov_id> renderizados de cards com
content idêntico. Causa: mov_id era canonical_event.id BIGINT volatil
entre re-materializes + sort tie-break por generated_at não-determinístico.

Fix: mov_id = cluster_id UUID (estavel) + sort (data, mov_id) determinístico.
Acceptance: mesma input → mesma prompt string byte-a-byte.
"""
from __future__ import annotations

import hashlib

import pytest

from src.agents.processo_synthesis.prompts import (
    _short_mov_id,
    _summarize_factsheet,
    build_processo_synthesis_prompt,
)
from src.agents.processo_synthesis.schemas import (
    ApoliceContextMin,
    MovFactSheetMin,
    ProcessoSynthesisRequest,
)


def _md5(s: str) -> str:
    return hashlib.md5(s.encode("utf-8", "ignore")).hexdigest()


# ── _short_mov_id ──────────────────────────────────────────────────────────


def test_short_mov_id_uuid_prefix_8_chars():
    """UUID 36 chars com hifens em 8/13/18/23 -> primeiros 8 chars."""
    uuid = "550e8400-e29b-41d4-a716-446655440000"
    assert _short_mov_id(uuid) == "550e8400"


def test_short_mov_id_numeric_returned_full():
    """Legacy numeric ID -> retorna inteiro (compat)."""
    assert _short_mov_id("136928") == "136928"


def test_short_mov_id_none_or_empty():
    assert _short_mov_id(None) == "?"
    assert _short_mov_id("") == "?"


def test_short_mov_id_almost_uuid_not_truncated():
    """36 chars mas sem hifens em pos correta -> NAO trunca."""
    fake = "x" * 36
    assert _short_mov_id(fake) == fake


# ── Determinismo do prompt builder ─────────────────────────────────────────


def _make_factsheet(mov_id: str, data: str, categoria: str = "despacho",
                   resumo: str = "ato qualquer") -> MovFactSheetMin:
    return MovFactSheetMin(
        mov_id=mov_id, data=data, categoria=categoria,
        relevancia_merito="baixa", resumo_ato=resumo,
    )


def _make_request(factsheets: list[MovFactSheetMin]) -> ProcessoSynthesisRequest:
    return ProcessoSynthesisRequest(
        processo_numero="10113464520194013800",
        classe="EXECUCAO FISCAL",
        tipo_judicial="fiscal",
        mov_factsheets=factsheets,
        apolices=[],
    )


def test_prompt_determinismo_same_input_same_hash():
    """Mesmo input (mesma list de factsheets em mesma ordem) -> mesmo prompt.
    Sanidade basica de determinismo."""
    fs = [
        _make_factsheet("uuid-1111", "2024-01-01"),
        _make_factsheet("uuid-2222", "2024-02-01"),
    ]
    p1 = build_processo_synthesis_prompt(_make_request(fs))
    p2 = build_processo_synthesis_prompt(_make_request(fs))
    assert _md5(p1) == _md5(p2)


def test_prompt_determinismo_input_reordered_same_hash():
    """Input em ORDEM DIFERENTE -> mesmo prompt (sort interno determinístico).

    Reproduz cenario do handoff: cascade Alto e Baixo passaram MESMOS cards
    em ordem fisica diferente (DB sort tie em generated_at). Apos fix
    (sort em data + mov_id), ordem nao importa.
    """
    fs_a = [
        _make_factsheet("aaa-2222", "2024-02-01", resumo="A"),
        _make_factsheet("bbb-1111", "2024-01-01", resumo="B"),
    ]
    fs_b = list(reversed(fs_a))  # ordem fisica diferente
    p_a = build_processo_synthesis_prompt(_make_request(fs_a))
    p_b = build_processo_synthesis_prompt(_make_request(fs_b))
    assert _md5(p_a) == _md5(p_b)


def test_prompt_determinismo_same_date_different_mov_ids():
    """Tie em data -> mov_id determina ordem (estavel)."""
    fs_a = [
        _make_factsheet("aaa-zzz", "2024-01-01", resumo="Z"),
        _make_factsheet("aaa-aaa", "2024-01-01", resumo="A"),
    ]
    fs_b = list(reversed(fs_a))
    p_a = build_processo_synthesis_prompt(_make_request(fs_a))
    p_b = build_processo_synthesis_prompt(_make_request(fs_b))
    assert _md5(p_a) == _md5(p_b)
    # Confirma que "A" (mov_id aaa-aaa) aparece ANTES de "Z" (mov_id aaa-zzz)
    # pq mov_id ASC tie-break
    pos_a = p_a.find("resumo: A") if "resumo: A" in p_a else p_a.find("A")
    pos_z = p_a.find("Z")
    assert 0 <= pos_a < pos_z


def test_prompt_has_suspensao_transito_rule():
    """L0 DADO v2.4: o prompt deve conter a REGRA DE SUSPENSAO E TRANSITO com a distincao
    merito-vs-execucao (IRDR/anulacao vs Acao Rescisoria/RJ). Guarda contra revert silencioso."""
    p = build_processo_synthesis_prompt(_make_request([
        _make_factsheet("uuid-1", "2024-01-01"),
    ]))
    assert "REGRA DE SUSPENSAO E TRANSITO" in p
    for token in ("IRDR", "Acao Rescisoria", "Recuperacao Judicial", "CUMPRIMENTO"):
        assert token in p, f"prompt perdeu o token {token!r}"


def test_summarize_factsheet_renders_short_mov_id():
    """_summarize_factsheet usa _short_mov_id no #<id>."""
    fs = _make_factsheet("550e8400-e29b-41d4-a716-446655440000", "2024-01-01")
    line = _summarize_factsheet(fs)
    assert "#550e8400" in line
    # NAO renderiza UUID full (36 chars) — confunde leitura
    assert "550e8400-e29b-41d4-a716-446655440000" not in line


def test_summarize_factsheet_legacy_numeric_id_preserved():
    """Cards antigos com mov_id numeric (pre-Fase 2) ainda renderizam."""
    fs = _make_factsheet("136928", "2024-01-01")
    line = _summarize_factsheet(fs)
    assert "#136928" in line

"""Testes do L2 v2.3 SEM CAP (REV4 2026-06-12, decisao Elton).

Cobre: timeline completa sem corte (cap-50 removido), peticao 1P (entrada
mais antiga) sempre presente — cenario que o cap cortava em 2/2 procs reais
do censo —, instrucoes novas (peticao + split por doc), instrucoes mortas de
"autos raw" ausentes, e render sem truncagem de resumo_ato.
"""
from __future__ import annotations

from src.agents.processo_synthesis.prompts import (
    build_probabilidade_exito_prompt,
    build_processo_synthesis_prompt,
)
from src.agents.processo_synthesis.schemas import (
    MovFactSheetMin,
    ProcessoSynthesisRequest,
)


def _fs(mov_id: str, data: str, resumo: str = "ato") -> MovFactSheetMin:
    return MovFactSheetMin(
        mov_id=mov_id, data=data, categoria="despacho",
        relevancia_merito="baixa", resumo_ato=resumo,
    )


def _req(factsheets: list[MovFactSheetMin]) -> ProcessoSynthesisRequest:
    return ProcessoSynthesisRequest(
        processo_numero="80383191420228050001",
        classe="EXECUCAO FISCAL",
        tipo_judicial="fiscal",
        mov_factsheets=factsheets,
    )


def test_sem_cap_60_movs_todas_renderizadas():
    """>50 movs -> TODAS no prompt, sem nota de omissao (cap-50 morto)."""
    fs = [
        _fs(f"uuid-{i:04d}", f"2024-01-{(i % 28) + 1:02d}", resumo=f"ato numero {i}")
        for i in range(60)
    ]
    p = build_processo_synthesis_prompt(_req(fs))
    assert "omitidas" not in p
    assert all(f"ato numero {i}" in p for i in range(60))
    assert "movs_processed = 60" in p


def test_peticao_mais_antiga_sempre_no_prompt():
    """Card 1P (data minima) sobrevive com 59 movs mais novas — o cenario
    exato que o cap-50 cortava (censo 2026-06-12: 2/2 procs reais)."""
    fs = [_fs(f"uuid-{i:04d}", "2025-01-01", resumo=f"mov numero {i}") for i in range(59)]
    fs.append(
        _fs("peticao-80383191420228050001", "2022-03-29",
            resumo="Trata-se de Execucao Fiscal movida pelo Estado da Bahia")
    )
    p = build_processo_synthesis_prompt(_req(fs))
    assert "#peticao-80383191420228050001" in p
    # entrada mais antiga -> primeira do timeline
    assert p.find("Trata-se de Execucao Fiscal") < p.find("mov numero 0")


def test_instrucoes_peticao_e_split_presentes():
    p = build_processo_synthesis_prompt(_req([_fs("uuid-1", "2024-01-01")]))
    assert "PETICAO INICIAL" in p
    assert "peticao-<numero>" in p
    assert "SPLIT POR DOCUMENTO" in p
    assert "'<id>:<doc>'" in p
    assert "NUNCA entra em decisao_vigente" in p


def test_autos_raw_instrucoes_mortas_ausentes():
    """v2.3: zero mencoes a 'autos raw' (request nunca teve o campo no
    caminho vivo; ex-REGRA F removida, G ESTABILIDADE renumerada pra F)."""
    p = build_processo_synthesis_prompt(_req([_fs("uuid-1", "2024-01-01")]))
    assert "autos raw" not in p
    assert "ESTABILIDADE TEMPORAL" in p  # ex-G, agora F — nao sumiu junto
    assert "(REGRA F)" in p              # lembrete_final aponta pra letra nova


def test_resumo_ato_sem_truncagem():
    longo = "x" * 1500
    p = build_processo_synthesis_prompt(_req([_fs("uuid-1", "2024-01-01", resumo=longo)]))
    assert longo in p


def test_prob_exito_sem_cap():
    fs = [
        _fs(f"uuid-{i:04d}", "2024-01-01", resumo=f"ato numero {i}")
        for i in range(60)
    ]
    p = build_probabilidade_exito_prompt(_req(fs))
    assert all(f"ato numero {i}" in p for i in range(60))

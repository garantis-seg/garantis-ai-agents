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


# ── Filtro de relevância p/ processo GIGANTE (2026-06-20, insight Elton) ──
# >200 movs: dropa procedural ruido/baixa (o L1 JÁ julgou), mantém TODO sinal +
# cauda recente. Evita o TIMEOUT_LAYER2 sem cortar decisão/garantia/petição.

def test_processo_gigante_filtra_procedural_mantem_sinal():
    fs = [
        # petição inicial (mais antiga) — sempre mantida
        MovFactSheetMin(mov_id="peticao-80383191420228050001", data="2020-01-01",
                        relevancia_merito="alta", resumo_ato="PETICAO INICIAL da execucao"),
        # decisão relevante ENTERRADA no meio — mantida onde quer que esteja
        MovFactSheetMin(mov_id="dec-meio", data="2021-06-01", relevancia_merito="alta",
                        resumo_ato="SENTENCA improcedente",
                        decisao={"tem_decisao": True, "natureza": "improcedente"}),
        # evento de garantia — mantido mesmo se relevância media
        MovFactSheetMin(mov_id="gar-1", data="2021-07-01", relevancia_merito="media",
                        resumo_ato="oferta de seguro garantia",
                        evento_garantia={"tipo": "apresentacao"}),
    ]
    # 250 movs procedurais ruido (datas crescentes c/ i) — dropadas, menos a cauda recente
    for i in range(250):
        fs.append(MovFactSheetMin(
            mov_id=f"proc-{i:04d}", data=f"2022-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}",
            relevancia_merito="ruido", categoria="despacho",
            resumo_ato=f"intimacao procedural {i}"))
    p = build_processo_synthesis_prompt(_req(fs))
    assert "omitidas" in p                          # marcador (no silent cap)
    assert "#peticao-80383191420228050001" in p     # petição mantida (sem o bug REV4)
    assert "SENTENCA improcedente" in p             # decisão no meio mantida
    assert "oferta de seguro garantia" in p         # garantia mantida
    assert "intimacao procedural 0" not in p        # procedural antiga (ruido) dropada
    assert "intimacao procedural 249" in p          # cauda recente mantida


def test_processo_no_limite_nao_filtra():
    """<= threshold: render TUDO (REV4 intacto), sem marcador."""
    fs = [_fs(f"uuid-{i:04d}", f"2024-01-{(i % 28) + 1:02d}", resumo=f"ato {i}")
          for i in range(200)]
    p = build_processo_synthesis_prompt(_req(fs))
    assert "omitidas" not in p
    assert all(f"ato {i}" in p for i in range(200))

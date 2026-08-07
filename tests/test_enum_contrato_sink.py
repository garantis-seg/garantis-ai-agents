"""Contrato de enum entre o miner (ESTE repo) e o sink (garantis-shared).

O bug que este teste existe pra impedir que reabra: `CdaPeticao.ente` nasceu com
`federal_pgfn` (2026-06-11) e o mapa do `peticao_sink` foi escrito com a chave
`federal` no dia seguinte. Ninguem cruzou os dois lados por ~2 meses — 670
referencias de CDA federal foram gravadas com `tipo_documento='desconhecido'` e a
ponte `mesma_cda` perdeu 115 inscricoes contra o ancora do `inscricao_bridge`
(a ponte casa por `objeto_id`, entao tipo errado = no separado = conexao perdida).

⚠️ ESTE e o unico repo onde os dois lados sao importaveis: `garantis-ai-agents`
depende de `garantis-shared`, nunca o contrario — um teste no shared inverteria a
seta. O preco: ele roda contra o WHEEL PINADO em requirements.txt, entao valor novo
no enum quebra IMEDIATO (o caso que importa), mas mudanca do lado do sink so aparece
no PR que bumpa o pin.

Importa `peticao_contract` (modulo SEM dependencias), nao `peticao_sink` — o sink puxa
psycopg2, que este repo nao instala de proposito. Sem isso o teste viraria
`importorskip`, e gate que pula em silencio e pior que gate vermelho.

⛔ NAO troque estas assercoes por uma lista de strings escrita a mao. Foi exatamente
o que `garantis-shared/tests/test_peticao_sink_guards.py` fez com `PAPEIS_ARESTA`
(snapshot do consumidor, sem o produtor do outro lado) — e foi por isso que o `ente`
passou batido.
"""
from typing import get_args

from garantis_shared.engine_v6.persistence.peticao_contract import (
    ADMIN_TIPO_TO_NO,
    ENTE_TO_CDA,
    PAPEIS_ARESTA,
)

from src.agents.mov_factsheet.schemas import CDABlock          # v3.1 — ramo ainda vivo
from src.agents.mov_factsheet.schemas_v4 import (
    CdaPeticao,
    ProcessoAdminCitado,
    ProcessoCitado,
)


def _enum_values(model, field: str) -> set[str]:
    """Valores do Literal do campo, atravessando o Optional[...] por fora."""
    pendentes = [model.model_fields[field].annotation]
    achados: set[str] = set()
    while pendentes:
        for arg in get_args(pendentes.pop()):
            achados.add(arg) if isinstance(arg, str) else pendentes.append(arg)
    assert achados, f"{model.__name__}.{field} nao e um Literal de strings"
    return achados


def test_ente_da_cda_cobertura_total_nos_dois_sentidos():
    """enum ⊆ dict (o bug de 2026-06) E dict ⊆ enum (chave morta que ninguem alcanca)."""
    enum = _enum_values(CdaPeticao, "ente")
    mapa = set(ENTE_TO_CDA)

    assert not (enum - mapa), (
        f"valor novo no miner sem entrada no sink: {sorted(enum - mapa)}. "
        "Toda CDA com esse ente vira tipo_documento='desconhecido' EM SILENCIO e sai "
        "da ponte mesma_cda. Adicione a chave em ENTE_TO_CDA."
    )
    assert not (mapa - enum), (
        f"chave inalcancavel no sink: {sorted(mapa - enum)}. O miner nunca emite esse "
        "valor — remova, ou o proximo leitor vai achar que ela cobre algo."
    )


def test_ente_do_schema_v3_nao_divergiu_do_v4():
    """O ramo v3.1 (`use_v4=False`, agent.py) segue vivo e escreve no MESMO sink."""
    assert _enum_values(CDABlock, "ente") == _enum_values(CdaPeticao, "ente")


def test_as_3_colunas_do_no_sao_do_dominio_certo():
    """A armadilha do one-liner: a esfera saia do MESMO dict que o tipo (`esfera = ente
    if ente in _ENTE_TO_TIPO`), entao mapear so o tipo passaria a gravar
    esfera='federal_pgfn' em leads.cdas — valor fora do dominio da coluna. Pra
    `estadual`/`municipal` a esfera COINCIDE com a chave; o invariante nao e 'difere da
    chave', e 'pertence ao dominio'. As 3 colunas andam juntas porque sao exatamente as
    do uq_cdas_dedup: escrever 2 de 3 aponta pra um NO diferente."""
    for ente, (tipo, esfera, origem) in ENTE_TO_CDA.items():
        assert esfera.lower() in ("estadual", "municipal", "federal"), f"{ente}: {esfera!r}"
        assert tipo in ("cda_estadual", "cda_municipal", "inscricao_pgfn"), f"{ente}: {tipo!r}"
        # 'PGFN' = o que services/inscricao_bridge.py (execucao-fiscal) grava no MESMO no.
        # Divergir aqui recria o id-split, so na direcao bridge-depois-de-peticao.
        esperado = "PGFN" if tipo == "inscricao_pgfn" else None
        assert origem == esperado, f"{ente}: origem_fazenda={origem!r}, esperado {esperado!r}"


def test_tipo_do_admin_cobertura_total_nos_dois_sentidos():
    """O TERCEIRO enum, que ate 2026-08-07 nao tinha contrato nenhum.

    O sink coercia com `if tipo not in ("paf","tit_sp"): tipo = "paf"` — literal
    duplicado do enum, escrito a mao, exatamente o anti-padrao que o `ente` provou ser
    caro. Valor novo aqui sem entrada no mapa nao "quebra": grava esfera FEDERAL num PA
    estadual, em silencio, e o card da tela diz "ADM. FED.".
    """
    enum = _enum_values(ProcessoAdminCitado, "tipo")
    mapa = set(ADMIN_TIPO_TO_NO)

    assert not (enum - mapa), (
        f"valor novo no miner sem entrada no sink: {sorted(enum - mapa)}. Todo admin com "
        "esse tipo e gravado como 'paf'/federal EM SILENCIO. Adicione em ADMIN_TIPO_TO_NO."
    )
    assert not (mapa - enum), (
        f"chave inalcancavel no sink: {sorted(mapa - enum)}. O miner nunca emite esse "
        "valor — remova, ou o proximo leitor vai achar que ela cobre algo."
    )


def test_o_no_do_admin_e_do_dominio_certo():
    """Gemeo do teste das 3 colunas da CDA: `tipo` vira coluna E chave do UNIQUE, e
    esfera/uf sao afirmacoes sobre o mundo. UF fixa so onde o proprio enum a nomeia —
    'PA estadual' e qualquer fisco estadual, cravar 'SP' inventaria UF pra um PA do RJ."""
    for tipo, (esfera, uf) in ADMIN_TIPO_TO_NO.items():
        assert esfera in ("federal", "estadual", "municipal"), f"{tipo}: {esfera!r}"
        assert uf is None or (len(uf) == 2 and uf.isupper()), f"{tipo}: {uf!r}"
        assert (uf is not None) == tipo.endswith("_sp"), (
            f"{tipo}: uf={uf!r}. UF fixa so em tipo que NOMEIA a UF."
        )


def test_papel_da_aresta_e_exclusao_NOMEADA_nao_esquecimento():
    """`papel` e coberto PARCIALMENTE de proposito (jurisprudencia/incerto nunca viram
    aresta — docstring do sink). O teste fixa QUAIS ficam de fora, pra um valor NOVO no
    enum nao entrar mudo nessa mesma vala."""
    fora_por_design = {"jurisprudencia", "incerto"}
    enum = _enum_values(ProcessoCitado, "papel")

    assert PAPEIS_ARESTA <= enum, f"papel morto no sink: {sorted(PAPEIS_ARESTA - enum)}"
    assert enum - PAPEIS_ARESTA == fora_por_design, (
        f"papel novo no miner: {sorted(enum - PAPEIS_ARESTA - fora_por_design)}. Decida "
        "explicitamente se ele vira aresta (PAPEIS_ARESTA) ou entra nesta lista."
    )

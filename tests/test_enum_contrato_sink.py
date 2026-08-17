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

from garantis_shared.engine_v6.layer1_policy_factsheet.gatekeeper_contract import (
    GATEKEEPER_EVENTO_TIPOS,
)
from garantis_shared.engine_v6.persistence.peticao_contract import (
    ADMIN_TIPO_TO_NO,
    ENTE_TO_CDA,
    PAPEIS_ARESTA,
)

from src.agents.mov_factsheet.schemas import CDABlock          # v3.1 — ramo ainda vivo
from src.agents.mov_factsheet.schemas_v4 import (
    CdaPeticao,
    EventoGarantiaV4,
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
    esfera/uf sao afirmacoes sobre o mundo. UF gravada so onde o proprio enum a nomeia —
    'PA estadual' e qualquer fisco estadual, cravar 'SP' inventaria UF pra um PA do RJ.

    ⚠️ `pa` (v1.5) e a UNICA entrada com esfera NULL, e isso e o CONTRATO, nao buraco:
    ele e o default do miner e significa 'o documento nao disse a esfera'. A lista
    abaixo e NOMEADA de proposito — tipo novo com esfera NULL tem que ser uma decisao,
    nao um esquecimento, senao volta a virar afirmacao por omissao (que e exatamente o
    que o default `paf` fazia ate 2026-08-13).

    ⚠️ **A implicacao CAIU PRA UM LADO SO em 2026-08-14** (garantis-shared#362). Ate
    aqui a assercao de UF era `(uf is not None) == tipo.endswith('_sp')` — BI-direcional,
    e por isso ela afirmava DUAS coisas:
      (a) tipo COM uf tem de NOMEAR a uf   -> continua valendo, e e a metade que pega o
          mutante que este teste existe pra pegar (`pa_estadual` ganhar `fixed_uf='SP'`);
      (b) tipo que nomeia `_sp` tem de TER uf -> **caiu**. `tit_sp` era o unico rotulo do
          sistema que gravava UF, e a gravava a partir do NOME do enum, nao de evidencia:
          `ProcessoAdminCitado` (abaixo) tem `numero`, `tipo`, `contexto`, `par_numero` e
          NENHUM campo de UF. Medido em prod sobre as 266 refs de nos `tit_sp`: 139
          (52,3%) estao fora do TJ-SP, 98 delas no tribunal ESTADUAL de OUTRO estado.

    ⛔ A assercao abaixo nasceu ORDER-FREE (`uf is None or tipo.endswith('_sp')`) porque
    este repo roda o teste contra o WHEEL PINADO (`requirements.txt`): enquanto o pin
    estivesse no velho (`tit_sp` -> ('estadual','SP')), a forma estrita deixaria o gate
    fail-closed do `cloudbuild-deploy` VERMELHO em master.
    ✅ **O pin subiu pra 1.479.0 em 2026-08-17** (ai-agents#169, o bump que o bot abriu
    depois do merge do garantis-shared#362), entao a forma estrita entrou. Ela e a que
    importa: a order-free ACEITAVA `tit_sp` reganhar 'SP' — ou seja, deixava de pegar
    exatamente a regressao que este pacote existe pra impedir. Ela so podia entrar DEPOIS
    do bump, e o bump ja esta em master."""
    sem_esfera_por_design = {"pa"}
    assert sem_esfera_por_design <= set(ADMIN_TIPO_TO_NO), (
        "o generico sumiu do mapa: sem ele o sink volta a ter que ESCOLHER uma esfera "
        "pro caso 'nao sei', e a unica escolha disponivel afirma federal."
    )
    for tipo, (esfera, uf) in ADMIN_TIPO_TO_NO.items():
        if tipo in sem_esfera_por_design:
            assert (esfera, uf) == (None, None), (
                f"{tipo}: {esfera!r}/{uf!r}. O generico nao afirma esfera NEM uf."
            )
            continue
        assert esfera in ("federal", "estadual", "municipal"), f"{tipo}: {esfera!r}"
        assert uf is None, (
            f"{tipo}: uf={uf!r}. NENHUM rotulo grava UF — o miner nao emite UF nenhuma "
            "(`ProcessoAdminCitado` nao tem o campo), entao qualquer valor aqui vem do "
            "NOME do enum e nao de evidencia. `tit_sp` foi o ultimo a cair (2026-08-14)."
        )


def test_o_DEFAULT_do_miner_nao_afirma_esfera():
    """⛔ MUTANTE: voltar `default="paf"` reprova AQUI, sem precisar de LLM.

    Ate a v1.4 omissao e afirmacao gravavam o MESMO byte (`paf`), entao nenhuma consulta
    conseguia separar 'o modelo disse federal' de 'o modelo nao disse nada' — e a tela
    dizia "Adm. Fed." pros dois. Medido: 8 badges errados em 6 conexos. O invariante que
    fica: o DEFAULT tem que ser um valor que NAO afirma esfera."""
    padrao = ProcessoAdminCitado(numero="017.00100686/2026-51").tipo
    assert ADMIN_TIPO_TO_NO[padrao] == (None, None), (
        f"o default do miner e {padrao!r}, que afirma "
        f"esfera={ADMIN_TIPO_TO_NO[padrao][0]!r} sem o texto ter dito nada."
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


def test_evento_da_garantia_e_exclusao_NOMEADA_nao_esquecimento():
    """O QUARTO enum — e a 2a vez que a MESMA classe de bug mordeu neste sink.

    `_GATEKEEPER_EVENTO_TIPOS` foi escrito em 2026-05-26 contra o enum v3 (7 valores);
    `acionamento` entrou no v4 em 2026-06-10; ninguem cruzou os dois lados por ~2 meses.
    Ficou de fora justamente o sinal MAIS forte de que ha apolice em jogo (ordem de
    EXECUTAR a garantia): 260 cards / 55 PNs em prod. Fechado no garantis-shared#310.

    Custou US$0,00 por ACIDENTE, nao por contrato: 253 dos 260 cards ja entravam pelo
    braco do `subtipo` (`_row_to_card` faz `tipo_garantia = evento_garantia_subtipo`).
    Esse resgate NAO existe na perna JSONB do `_load_mov_cards_by_doc`, e a poda e
    PERMANENTE na outra direcao (`_persist_gatekept` grava no_policies e
    `_already_extracted` nunca reabre). Ou seja: o proximo esquecimento paga.
    """
    fora_por_design = {"nenhum"}
    enum = _enum_values(EventoGarantiaV4, "tipo")

    assert enum - GATEKEEPER_EVENTO_TIPOS == fora_por_design, (
        f"tipo novo no miner sem entrada no gatekeeper: "
        f"{sorted(enum - GATEKEEPER_EVENTO_TIPOS - fora_por_design)}. Doc com esse evento "
        "so extrai se o SUBTIPO ou a keyword salvarem, e a poda e PERMANENTE. Decida "
        "explicitamente: entra em GATEKEEPER_EVENTO_TIPOS ou nesta lista."
    )
    assert GATEKEEPER_EVENTO_TIPOS <= enum, (
        f"chave morta no gatekeeper: {sorted(GATEKEEPER_EVENTO_TIPOS - enum)}. O miner "
        "nunca emite esse valor — foi assim que o `reforco` ACENTUADO viveu ali desde "
        "2026-05 com 0 rows em prod."
    )

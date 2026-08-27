"""Trava de corpo do L1 (card 869ent0g8): sem CORPO e sem DOC ANEXO nao ha decisao.

O caso-alvo e literal: `"Julgado - Julgado improcedente o pedido"` (39 chars), a etiqueta
do catalogo do jusbrasil que cunhou 3.964 cards de decisao em prod, em 810 processos /
227 meritos. O teste NAO chama LLM nem banco — a trava e mecanica de proposito.

⚰️ A trava era gated por `L1_DECISAO_EXIGE_CORPO`, default OFF. A flag SAIU em 2026-08-27
(card 869entgbc) e com ela os 3 testes que provavam o mundo desligado
(`test_flag_off_e_byte_identico`, `test_prompt_flag_off_mantem_o_anticorpo` e o parametrize
das formas negativas). ⛔ Os dois primeiros guardavam um mundo que nao existe mais — prod
rodava ON desde 23/08, entao eles passavam VERDE afirmando o contrario do que producao
fazia. O terceiro NAO era um teste desta trava: era o unico oraculo do parser do
`flag_enabled`, e mudou de casa em vez de morrer (`tests/test_feature_flags.py`).
"""
from src.agents.mov_factsheet.agent import (
    _build_card_v4,
    _sem_corpo,
    _zerar_decisao,
)
from src.agents.mov_factsheet.prompts_v4 import (
    CORPO_MIN_CHARS,
    build_mov_factsheet_prompt_v4,
)
from src.agents.mov_factsheet.schemas import DocAnexado, MovInput, ProcessoContext

# A string real, do merito 13294 (processo 10020587). 39 chars.
ROTULO = "Julgado - Julgado improcedente o pedido"

# Um ato REAL curto — o custo declarado da trava. Cai junto, e isso e sabido:
# no censo de 1.663 strings, ATO_REAL <=60 chars vale 2,6% dos cards.
ATO_REAL_CURTO = "denego a seguranca"


def _mov(texto: str) -> MovInput:
    return MovInput(mov_id="m1", data="2024-11-11", tipo="Andamento - Julgado", texto=texto)


def _card_llm() -> dict:
    """O que a LLM devolve HOJE pro ROTULO (verificado em prod: 4 cards fantasma)."""
    return {
        "resumo_ato": "Pedido julgado improcedente.",
        "tipo_doc": "sentenca",
        "relevancia_merito": "alta",
        "decisao": {
            "tem_decisao": True,
            "natureza": "improcedente",
            "instancia": "1g",
            "dispositivo": "Julgado improcedente o pedido",
            "transito_certificado": False,
        },
    }


# ── _sem_corpo: a decisao mecanica, isolada ───────────────────────────────────
def test_sem_corpo_rotulo_curto_sem_doc():
    assert _sem_corpo(_mov(ROTULO), [])


def test_com_doc_anexo_nao_e_sem_corpo():
    """A mesma etiqueta COM documento anexado NAO e alcancada — 2.375 dos 6.530 cards
    da populacao bruta estao neste caso, e por isso nao entram na correcao."""
    doc = DocAnexado(doc_key="d1", tipo_doc="sentenca", text_content="x" * 5000)
    assert not _sem_corpo(_mov(ROTULO), [doc])


def test_texto_longo_sem_doc_nao_e_sem_corpo():
    assert not _sem_corpo(_mov("y" * (CORPO_MIN_CHARS + 1)), [])


def test_borda_do_corte_e_inclusiva():
    assert _sem_corpo(_mov("y" * CORPO_MIN_CHARS), [])
    assert not _sem_corpo(_mov("y" * (CORPO_MIN_CHARS + 1)), [])


def test_texto_vazio_ou_so_espaco():
    assert _sem_corpo(_mov(""), [])
    assert _sem_corpo(_mov("   \n  "), [])


# ── a trava aplicada ao card ──────────────────────────────────────────────────
def test_apaga_a_decisao_fabricada():
    card = _build_card_v4(_card_llm(), _mov(ROTULO), sem_corpo=True)
    d = card["decisao"]
    assert d["tem_decisao"] is False
    assert d["natureza"] is None and d["instancia"] is None
    assert d["dispositivo"] is None
    # o G6 roda DEPOIS da trava: peca_pivo tem de sair coerente, nao residual.
    assert card["peca_pivo"]["e_pivo"] is False


def test_nao_toca_card_com_corpo():
    card = _build_card_v4(_card_llm(), _mov("z" * 400), sem_corpo=False)
    assert card["decisao"]["tem_decisao"] is True
    assert card["decisao"]["natureza"] == "improcedente"


def test_transito_certificado_sobrevive_a_trava():
    """Certidao de transito e fato PROPRIO, com guard proprio no L2 — a trava e sobre
    `tem_decisao`, nao sobre o transito. Se isto quebrar, a trava passou do escopo."""
    parsed = _card_llm()
    parsed["decisao"]["transito_certificado"] = True
    card = _build_card_v4(parsed, _mov("Transitado em julgado"), sem_corpo=True)
    assert card["decisao"]["tem_decisao"] is False
    assert card["decisao"]["transito_certificado"] is True


def test_travar_e_idempotente():
    card = {"decisao": {"tem_decisao": True, "natureza": "procedente"}}
    _zerar_decisao(card)
    _zerar_decisao(card)
    assert card["decisao"] == {"tem_decisao": False, "natureza": None}


def test_travar_tolera_card_sem_bloco_decisao():
    card = {"resumo_ato": "x"}
    _zerar_decisao(card)          # nao levanta
    assert "decisao" not in card


# ── o anticorpo estetico saiu do prompt ──────────────────────────────────────
def _prompt() -> str:
    return build_mov_factsheet_prompt_v4(
        ProcessoContext(cnj="1002058-77.2022.8.26.0053"),
        _mov(ROTULO),
        documentos_anexados=[],
    )


def test_prompt_NAO_tem_mais_o_anticorpo_estetico():
    """Criterio 4 do card: o conserto REMOVE o anticorpo, nao empilha em cima dele.

    ⛔ O `not in` e a metade que importa e nao e redundante com o `in`: o anticorpo pedia
    ao modelo um juizo de GOSTO sobre a entrada ("Snippet generico => tem_decisao=false"),
    e ele falha por construcao no caso-alvo — o rotulo do catalogo NAO e generico. Se
    alguem re-introduzir a frase, este assert cai."""
    p = _prompt()
    assert "Snippet gen" not in p
    assert "texto INTEIRO" in p


def test_ato_real_curto_e_o_custo_declarado():
    """⚠️ NAO e um bug: a trava e cega a voz do juiz e derruba tambem o dispositivo
    curto e verdadeiro. Medido: 2,6% dos cards <=60 chars. Se um dia isso for
    inaceitavel, o discriminador e a VOZ (1a pessoa), como no guard do L2 —
    `transito_classifier._VOZ_DO_JUIZ`. Este teste existe pra que a perda seja
    VISIVEL no diff, nunca descoberta em prod."""
    assert _sem_corpo(_mov(ATO_REAL_CURTO), [])
    card = _build_card_v4(_card_llm(), _mov(ATO_REAL_CURTO), sem_corpo=True)
    assert card["decisao"]["tem_decisao"] is False


# ── 3o estado: documento EXISTE mas nao foi admitido (869enu94n) ──────────────
def _mov_ilegivel(texto: str, n: int = 1) -> MovInput:
    """Mov curta, SEM doc admissivel, mas com `n` docs que existem e nao passaram no
    filtro (sem texto E sem gcs_url) — o carimbo vem do loader do shared."""
    return MovInput(mov_id="m1", data="2022-08-18", tipo="Andamento - Julgado",
                    texto=texto, docs_inadmissiveis=n)


def test_doc_ilegivel_nao_e_sem_corpo():
    """O caso do merito 17 (CVC): a `Sentenca Tipo A` existe, mas com has_text=false e
    gcs_url NULL. O rotulo e PONTEIRO pra peca real — nao pode ser apagado."""
    assert not _sem_corpo(_mov_ilegivel(ROTULO), [])


def test_sem_doc_nenhum_continua_sendo_sem_corpo():
    """O discriminador: 0 docs inadmissiveis = nao existe peca = afirmacao sem lastro."""
    assert _sem_corpo(_mov_ilegivel(ROTULO, n=0), [])


def test_campo_declarado_no_schema_senao_pydantic_descarta():
    """⛔ Guard da armadilha: pydantic v2 descarta campo NAO declarado em silencio, e o
    sinal viraria letra morta sem erro nenhum (mesma classe do bug da fundacao do
    Tomador). Este teste falha se alguem remover o campo do MovInput."""
    m = MovInput(**{"mov_id": "m1", "texto": ROTULO, "docs_inadmissiveis": 3})
    assert m.docs_inadmissiveis == 3


def test_nao_apaga_decisao_quando_doc_e_ilegivel():
    card = _build_card_v4(_card_llm(), _mov_ilegivel(ROTULO),
                          sem_corpo=_sem_corpo(_mov_ilegivel(ROTULO), []))
    assert card["decisao"]["tem_decisao"] is True
    assert card["decisao"]["natureza"] == "improcedente"

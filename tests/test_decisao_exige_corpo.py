"""Trava de corpo do L1 (card 869ent0g8): sem CORPO e sem DOC ANEXO nao ha decisao.

O caso-alvo e literal: `"Julgado - Julgado improcedente o pedido"` (39 chars), a etiqueta
do catalogo do jusbrasil que cunhou 3.964 cards de decisao em prod, em 810 processos /
227 meritos. O teste NAO chama LLM nem banco — a trava e mecanica de proposito.

⚠️ O flag e default OFF. Os testes de OFF sao os que provam "byte-identico em prod hoje".
"""
import pytest

from src.agents.mov_factsheet.agent import (
    _build_card_v4,
    _sem_corpo,
    _travar_decisao_sem_corpo,
)
from src.agents.mov_factsheet.prompts_v4 import (
    CORPO_MIN_CHARS,
    L1_DECISAO_EXIGE_CORPO,
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
def test_flag_off_e_byte_identico(monkeypatch):
    monkeypatch.delenv(L1_DECISAO_EXIGE_CORPO, raising=False)
    card = _build_card_v4(_card_llm(), _mov(ROTULO), sem_corpo=True)
    assert card["decisao"]["tem_decisao"] is True
    assert card["decisao"]["natureza"] == "improcedente"
    assert card["peca_pivo"]["e_pivo"] is True


def test_flag_on_apaga_a_decisao_fabricada(monkeypatch):
    monkeypatch.setenv(L1_DECISAO_EXIGE_CORPO, "true")
    card = _build_card_v4(_card_llm(), _mov(ROTULO), sem_corpo=True)
    d = card["decisao"]
    assert d["tem_decisao"] is False
    assert d["natureza"] is None and d["instancia"] is None
    assert d["dispositivo"] is None
    # o G6 roda DEPOIS da trava: peca_pivo tem de sair coerente, nao residual.
    assert card["peca_pivo"]["e_pivo"] is False


def test_flag_on_nao_toca_card_com_corpo(monkeypatch):
    monkeypatch.setenv(L1_DECISAO_EXIGE_CORPO, "true")
    card = _build_card_v4(_card_llm(), _mov("z" * 400), sem_corpo=False)
    assert card["decisao"]["tem_decisao"] is True
    assert card["decisao"]["natureza"] == "improcedente"


def test_transito_certificado_sobrevive_a_trava(monkeypatch):
    """Certidao de transito e fato PROPRIO, com guard proprio no L2 — a trava e sobre
    `tem_decisao`, nao sobre o transito. Se isto quebrar, a trava passou do escopo."""
    monkeypatch.setenv(L1_DECISAO_EXIGE_CORPO, "true")
    parsed = _card_llm()
    parsed["decisao"]["transito_certificado"] = True
    card = _build_card_v4(parsed, _mov("Transitado em julgado"), sem_corpo=True)
    assert card["decisao"]["tem_decisao"] is False
    assert card["decisao"]["transito_certificado"] is True


def test_travar_e_idempotente():
    card = {"decisao": {"tem_decisao": True, "natureza": "procedente"}}
    _travar_decisao_sem_corpo(card)
    _travar_decisao_sem_corpo(card)
    assert card["decisao"] == {"tem_decisao": False, "natureza": None}


def test_travar_tolera_card_sem_bloco_decisao():
    card = {"resumo_ato": "x"}
    _travar_decisao_sem_corpo(card)          # nao levanta
    assert "decisao" not in card


@pytest.mark.parametrize("valor", ["", "false", "0", "no"])
def test_flag_desligada_em_qualquer_forma(monkeypatch, valor):
    monkeypatch.setenv(L1_DECISAO_EXIGE_CORPO, valor)
    card = _build_card_v4(_card_llm(), _mov(ROTULO), sem_corpo=True)
    assert card["decisao"]["tem_decisao"] is True


# ── o anticorpo estetico sai do prompt sob o mesmo flag ───────────────────────
def _prompt(**env) -> str:
    return build_mov_factsheet_prompt_v4(
        ProcessoContext(cnj="1002058-77.2022.8.26.0053"),
        _mov(ROTULO),
        documentos_anexados=[],
    )


def test_prompt_flag_off_mantem_o_anticorpo(monkeypatch):
    monkeypatch.delenv(L1_DECISAO_EXIGE_CORPO, raising=False)
    assert "Snippet gen" in _prompt()


def test_prompt_flag_on_remove_o_anticorpo(monkeypatch):
    """Criterio 4 do card: o conserto REMOVE o anticorpo, nao empilha em cima dele."""
    monkeypatch.setenv(L1_DECISAO_EXIGE_CORPO, "true")
    p = _prompt()
    assert "Snippet gen" not in p
    assert "texto INTEIRO" in p


def test_ato_real_curto_e_o_custo_declarado(monkeypatch):
    """⚠️ NAO e um bug: a trava e cega a voz do juiz e derruba tambem o dispositivo
    curto e verdadeiro. Medido: 2,6% dos cards <=60 chars. Se um dia isso for
    inaceitavel, o discriminador e a VOZ (1a pessoa), como no guard do L2 —
    `transito_classifier._VOZ_DO_JUIZ`. Este teste existe pra que a perda seja
    VISIVEL no diff, nunca descoberta em prod."""
    monkeypatch.setenv(L1_DECISAO_EXIGE_CORPO, "true")
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


def test_flag_on_nao_apaga_decisao_quando_doc_e_ilegivel(monkeypatch):
    monkeypatch.setenv(L1_DECISAO_EXIGE_CORPO, "true")
    card = _build_card_v4(_card_llm(), _mov_ilegivel(ROTULO),
                          sem_corpo=_sem_corpo(_mov_ilegivel(ROTULO), []))
    assert card["decisao"]["tem_decisao"] is True
    assert card["decisao"]["natureza"] == "improcedente"

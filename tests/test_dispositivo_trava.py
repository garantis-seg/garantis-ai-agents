"""Trava de DISPOSITIVO do L1 (card 869enpem7): sem a ancora, o L1 nao afirma decisao.

## O que esta trava e, e o que ela NAO e

Ela NAO e a irma da trava de corpo (`test_decisao_exige_corpo.py`, card 869ent0g8). Sao dois
predicados independentes para a mesma conclusao, e nenhum contem o outro:

    corpo       -> "nao ha sobre o que decidir"        (a unidade nao tem texto nem doc)
    dispositivo -> "ha corpo e o card nao aponta onde" (o card ADMITE que nao sustenta)

O cohort desta trava e, por construcao, o que a de corpo NAO alcanca: card COM corpo, que
afirma veredito e nao consegue citar a frase que o enuncia.

## A regra ja existe — ela foi VIOLADA, nao mal escrita

`_REGRAS_CRUS` diz, palavra por palavra: *"Nao achou a frase no texto => dispositivo=null E
tem_decisao=false"*. O modelo cumpre parte do tempo e ninguem cobra no resto. Por isso o
conserto e MECANICO e nao mais uma frase no prompt: acrescentar regra a um prompt cuja regra
ja esta certa e o castelo-de-cartas que o card proibiu.

⚠️ O flag e default OFF. Os testes de OFF sao os que provam "byte-identico em prod hoje".

Run: pytest tests/test_dispositivo_trava.py -q
"""
import pytest

from src.agents.mov_factsheet.agent import (
    L1_DECISAO_EXIGE_DISPOSITIVO,
    _build_card_v4,
    _sem_dispositivo,
    _zerar_decisao,
)
from src.agents.mov_factsheet.agent import _sem_corpo
from src.agents.mov_factsheet.schemas import MovInput

# O caso-alvo, literal, do merito 13294: o card que dirige a banda tem natureza='procedente'
# e o resumo_ato INTEIRO e um AVISO que nao diz quem ganhou. A sentenca de verdade, no
# processo apontado (mesmo merito), diz extinto_sem_merito. O oposto.
AVISO = (
    "Comunicacao eletronica de sentenca proferida nos autos dos Embargos a Execucao "
    "Fiscal n 50094492720244047009/PR."
)

# Um dispositivo REAL — o controle positivo. 63% dos cards de decisao conseguem citar assim.
DISPOSITIVO_REAL = "julgo improcedentes os embargos a execucao fiscal"


def _mov(texto: str = AVISO) -> MovInput:
    """Mov COM corpo, sempre — pra que a trava de corpo nunca seja a causa do que
    observamos aqui. Sem isso os dois predicados ficariam indistinguiveis no teste."""
    return MovInput(
        mov_id="m1", data="2024-11-11", tipo="Andamento - Julgado",
        texto=texto + " " + "x" * 400,
    )


def _card_llm(dispositivo=None, **decisao) -> dict:
    """O que a LLM devolve. `dispositivo=None` e o defeito; preenchido e o controle."""
    d = {
        "tem_decisao": True,
        "natureza": "procedente",
        "instancia": "1g",
        "dispositivo": dispositivo,
        "transito_certificado": False,
    }
    d.update(decisao)
    return {
        "resumo_ato": AVISO,
        "tipo_doc": "sentenca",
        "relevancia_merito": "alta",
        "decisao": d,
    }


def test_o_mov_deste_arquivo_TEM_corpo():
    """⭐ Substitui a fixture `_corpo_off` (autouse), que desligava a trava de CORPO em
    todo este arquivo por env. A flag saiu em 2026-08-27 (card 869entgbc) e a trava agora
    e incondicional — ou seja, o isolamento **nao pode mais vir de env**, tem de vir do
    DADO. E o motivo declarado da fixture continua valendo palavra por palavra: se a trava
    de corpo alcancasse `_mov()`, um teste verde aqui estaria medindo a trava ERRADA.

    ⛔ Nao troque o texto de `_mov()` por um snippet curto: este assert cai, e ele e a
    unica coisa que separa os dois predicados neste arquivo."""
    assert not _sem_corpo(_mov(), [])
    assert not _sem_corpo(_mov(DISPOSITIVO_REAL), [])


# ── o predicado, isolado (sem LLM, sem banco) ─────────────────────────────────
def test_afirma_decisao_sem_apontar_a_frase():
    assert _sem_dispositivo(_card_llm())


def test_com_a_ancora_nao_e_alcancado():
    assert not _sem_dispositivo(_card_llm(dispositivo=DISPOSITIVO_REAL))


def test_quem_nao_afirma_decisao_esta_fora_do_escopo():
    """tem_decisao=false + dispositivo=null e o estado NORMAL de 10.348 dos 10.963 cards.
    Se o predicado pegasse esses, a trava seria um no-op caro sobre a base inteira."""
    assert not _sem_dispositivo(_card_llm(tem_decisao=False))


def test_string_vazia_conta_como_ausente():
    """'' passa pela validacao igual, mas some do `IS NULL` da leitura. Os dois significam
    'nao achei a frase' e tem de cair no mesmo lado."""
    assert _sem_dispositivo(_card_llm(dispositivo=""))
    assert _sem_dispositivo(_card_llm(dispositivo="   \n "))


def test_tolera_card_sem_bloco_decisao():
    assert not _sem_dispositivo({"resumo_ato": "x"})
    assert not _sem_dispositivo({"decisao": None})


# ── MUTANTE 4: flag desligada e a trava roda mesmo assim ──────────────────────
def test_flag_off_e_byte_identico(monkeypatch):
    monkeypatch.delenv(L1_DECISAO_EXIGE_DISPOSITIVO, raising=False)
    card = _build_card_v4(_card_llm(), _mov())
    assert card["decisao"]["tem_decisao"] is True
    assert card["decisao"]["natureza"] == "procedente"
    assert card["peca_pivo"]["e_pivo"] is True


@pytest.mark.parametrize("valor", ["", "false", "0", "no", "off"])
def test_flag_desligada_em_qualquer_forma(monkeypatch, valor):
    monkeypatch.setenv(L1_DECISAO_EXIGE_DISPOSITIVO, valor)
    assert _build_card_v4(_card_llm(), _mov())["decisao"]["tem_decisao"] is True


# ── MUTANTE 1: card sem ancora PASSA pela trava ───────────────────────────────
def test_flag_on_apaga_a_afirmacao_sem_ancora(monkeypatch):
    monkeypatch.setenv(L1_DECISAO_EXIGE_DISPOSITIVO, "true")
    d = _build_card_v4(_card_llm(), _mov())["decisao"]
    assert d["tem_decisao"] is False
    assert d["natureza"] is None and d["instancia"] is None


# ── MUTANTE 2: card COM ancora e zerado junto ─────────────────────────────────
def test_flag_on_preserva_quem_tem_a_ancora(monkeypatch):
    """O conserto e SUPERSET: os cards que ja funcionam tem de continuar identicos.
    Se este quebrar, a trava virou um apagador de decisao."""
    monkeypatch.setenv(L1_DECISAO_EXIGE_DISPOSITIVO, "true")
    card = _build_card_v4(_card_llm(dispositivo=DISPOSITIVO_REAL), _mov())
    assert card["decisao"]["tem_decisao"] is True
    assert card["decisao"]["natureza"] == "procedente"
    assert card["decisao"]["dispositivo"] == DISPOSITIVO_REAL
    assert card["peca_pivo"]["e_pivo"] is True


# ── MUTANTE 3: a trava roda DEPOIS do G6 ──────────────────────────────────────
def test_o_G6_ve_a_trava_e_sai_coerente(monkeypatch):
    """`aplicar_derivados_sujeito_indep` deriva categoria/peca_pivo/relevante DE
    `tem_decisao`. Se a trava rodasse depois dele, o card sairia com tem_decisao=false e
    peca_pivo=true — afirmando pela porta dos fundos exatamente o que a trava negou."""
    monkeypatch.setenv(L1_DECISAO_EXIGE_DISPOSITIVO, "true")
    card = _build_card_v4(_card_llm(), _mov())
    assert card["decisao"]["tem_decisao"] is False
    assert card["peca_pivo"]["e_pivo"] is False


# ── MUTANTE 5: transito_certificado cai junto ─────────────────────────────────
def test_transito_certificado_sobrevive(monkeypatch):
    """Certidao de transito e fato PROPRIO, com guard proprio no L2 — nao depende de haver
    decisao NESTA mov. Se cair junto, a trava passou do escopo (e e o mesmo contrato que a
    trava de corpo ja assinou)."""
    monkeypatch.setenv(L1_DECISAO_EXIGE_DISPOSITIVO, "true")
    card = _build_card_v4(
        _card_llm(transito_certificado=True), _mov("Transitado em julgado"),
    )
    assert card["decisao"]["tem_decisao"] is False
    assert card["decisao"]["transito_certificado"] is True


# ── os dois predicados sao INDEPENDENTES ──────────────────────────────────────
def test_a_trava_de_corpo_nao_liga_esta(monkeypatch):
    """⛔ A trava de CORPO (hoje incondicional) nao pode ligar a de dispositivo. Sao duas
    decisoes de risco separadas, e colapsa-las faria a barata governar a cara."""
    monkeypatch.delenv(L1_DECISAO_EXIGE_DISPOSITIVO, raising=False)
    card = _build_card_v4(_card_llm(), _mov())     # tem corpo => a de corpo nao alcanca
    assert card["decisao"]["tem_decisao"] is True


def test_as_duas_ligadas_e_idempotente(monkeypatch):
    monkeypatch.setenv(L1_DECISAO_EXIGE_DISPOSITIVO, "true")
    card = _build_card_v4(_card_llm(), _mov(), sem_corpo=True)
    assert card["decisao"]["tem_decisao"] is False
    assert card["decisao"]["natureza"] is None


# ── o log e a metade que MEDE: ele sai com a flag DESLIGADA ───────────────────
def test_o_log_sai_com_a_flag_off(monkeypatch, caplog):
    """⭐ A fase 0 mediu 4 ocorrencias, todas de 1 merito e 1 run — sem volume nao ha
    decisao de ligar. Se o log so saisse junto com a trava, o volume nunca apareceria e
    'contador em zero' ficaria indistinguivel de contador MUDO."""
    monkeypatch.delenv(L1_DECISAO_EXIGE_DISPOSITIVO, raising=False)
    with caplog.at_level("WARNING"):
        card = _build_card_v4(_card_llm(), _mov())
    assert card["decisao"]["tem_decisao"] is True          # nada mudou no card
    assert "L1_DECISAO_SEM_ANCORA" in caplog.text
    assert "travado=False" in caplog.text


def test_o_log_nao_sai_para_quem_tem_a_ancora(monkeypatch, caplog):
    monkeypatch.delenv(L1_DECISAO_EXIGE_DISPOSITIVO, raising=False)
    with caplog.at_level("WARNING"):
        _build_card_v4(_card_llm(dispositivo=DISPOSITIVO_REAL), _mov())
    assert "L1_DECISAO_SEM_ANCORA" not in caplog.text


def test_o_log_carimba_travado_quando_a_flag_esta_on(monkeypatch, caplog):
    monkeypatch.setenv(L1_DECISAO_EXIGE_DISPOSITIVO, "true")
    with caplog.at_level("WARNING"):
        _build_card_v4(_card_llm(), _mov())
    assert "travado=True" in caplog.text


def test_zerar_decisao_e_idempotente():
    card = {"decisao": {"tem_decisao": True, "natureza": "procedente"}}
    _zerar_decisao(card)
    _zerar_decisao(card)
    assert card["decisao"] == {"tem_decisao": False, "natureza": None}

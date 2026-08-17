"""Onda 9 — o VERIFICADOR CEGO (`verificar_par`), sem UMA chamada de LLM.

Todo teste aqui usa provider DUBLE. Testar julgamento de modelo em CI e teste
flaky disfarcado de garantia: o que se trava aqui e o CONTRATO — vocabulario
fechado, numeros computados em codigo, envelope obrigatorio, N declarado — e
justamente as partes que nao dependem de o modelo estar num dia bom.

O que cada bloco trava:

  1. Cegueira — o prompt nao recebe grafo, documento nem historico.
  2. Vocabulario fechado — 4 rotulos aceitos, qualquer outro REPROVA a resposta.
  3. `numeros_divergentes` em CODIGO — 723.910 x 723.810 e pego mesmo com o
     modelo dizendo `supported` (e o veredito e REBAIXADO).
  3b. Mesma quantia, formas diferentes — `500000.0` (repr de float do shared) e
     `R$ 500.000,00` sao o MESMO valor e nao podem virar divergencia.
  4. Envelope em campo — sem `objeto_da_confianca` => retry => erro tipado.
  5. DINCO — liga/desliga por env, N chamadas independentes, TODOS os votos
     gravados.
  6. Modelo != calculador (anti-conluio), no catalogo, nao-preview.
  7. Rota nova + COMPAT da rota antiga (`/auditar-evidencias` intacta).
"""
from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import src.agents.auditor_evidencias.agent as auditor_mod
import src.agents.auditor_evidencias.verificador as verif_mod
from src.agents.auditor_evidencias import auditar_evidencias, verificar_par
from src.agents.auditor_evidencias.verificador import (
    _numeros_divergentes,
    _valor_da_afirmacao,
    _valores_candidatos,
)
from src.agents.auditor_evidencias.verificador_prompts import (
    build_verificar_par_prompt,
)
from src.agents.auditor_evidencias.verificador_schemas import (
    MOTIVO_OK,
    MOTIVOS_TIPADOS,
    VEREDITOS,
)

# ── fixtures do dominio ─────────────────────────────────────────────────────

AFIRMACAO = "o IRPJ principal mantido e R$ 723.810.827,57"
TRECHO_OK = (
    "Pelo exposto, dou provimento parcial ao recurso para manter o IRPJ "
    "principal no valor de R$ 723.810.827,57."
)
#: A mutacao classica do G2: um DIGITO diferente, nao ruido de OCR em letra.
TRECHO_DIGITO_TROCADO = (
    "Pelo exposto, dou provimento parcial ao recurso para manter o IRPJ "
    "principal no valor de R$ 723.910.827,57."
)
#: OCR em LETRA: `81O` (letra O) no lugar de `810`. Tem que PASSAR.
TRECHO_OCR_LETRA = "manter o IRPJ principal no valor de R$ 723.81O.827,57."


def _resposta(veredito="supported", motivo_tipado=MOTIVO_OK, **extra) -> str:
    corpo = {
        "veredito": veredito,
        "motivo_tipado": motivo_tipado,
        "motivo": "o trecho traz o valor com a qualificacao de principal mantido",
        "confianca": 0.88,
        "objeto_da_confianca": "de que este trecho sustenta esta afirmacao",
    }
    corpo.update(extra)
    return json.dumps(corpo)


class _FakeProvider:
    """Provider duble: devolve textos em fila, gravando TODOS os prompts.

    Guarda a lista inteira de prompts (nao so o ultimo) porque o DINCO faz N
    chamadas e o que o teste precisa provar e justamente que sao N, e que sao
    INDEPENDENTES — nenhuma cita as outras.
    """

    def __init__(self, textos, cost: float = 0.001, model_out: str = "gemini-3.1-flash-lite"):
        self._textos = [textos] if isinstance(textos, str) else list(textos)
        self._i = 0
        self._cost = cost
        self._model_out = model_out
        self.prompts: list[str] = []

    async def agenerate(self, **kwargs):
        self.prompts.append(kwargs.get("prompt", ""))
        # Ultimo texto se repete: o teste declara so o que lhe importa.
        texto = self._textos[min(self._i, len(self._textos) - 1)]
        self._i += 1
        return SimpleNamespace(
            text=texto, model=self._model_out,
            input_tokens=300, output_tokens=80,
            metadata={"cost_usd": self._cost, "provider": "gemini"},
        )

    @property
    def n_chamadas(self) -> int:
        return len(self.prompts)


def _mock_provider(monkeypatch, textos, **kw) -> _FakeProvider:
    fake = _FakeProvider(textos, **kw)
    monkeypatch.setattr(verif_mod, "create_provider", lambda *_a, **_k: fake)
    return fake


def _rodar(coro):
    return asyncio.run(coro)


def _req(afirmacao=AFIRMACAO, trecho=TRECHO_OK, **kw) -> dict:
    return {"afirmacao": afirmacao, "trecho": trecho, **kw}


def _dinco_off(monkeypatch):
    """Estado default explicito. Sem isto, um env do shell decide o teste."""
    monkeypatch.delenv("FICHAS_DINCO_ENABLED", raising=False)
    monkeypatch.delenv("SELF_CONSISTENCY_N", raising=False)


# ══ 1. Cegueira ═════════════════════════════════════════════════════════════

def test_prompt_recebe_so_o_par():
    """O verificador nao pode ver grafo, documento inteiro nem quem escreveu.

    E a medicao do HALLMARK (FP ~5x com verificador contextualizado) virando
    contrato: se alguem adicionar `celulas` ou `documentos` ao prompt "para
    ajudar", este teste cai.
    """
    p = build_verificar_par_prompt(AFIRMACAO, TRECHO_OK)
    assert AFIRMACAO in p and TRECHO_OK in p
    for proibido in ("celula_id", "grafo", "rodadas_anteriores", "premissas_v3",
                     "documentos", "evidencias a julgar"):
        assert proibido not in p.lower(), f"prompt do cego vazou contexto: {proibido}"


def test_prompt_diz_que_partial_e_irrelevant_existem():
    """Sem isso o modelo colapsa em supported/contradicted — e as filas de
    refinamento e de retrieval, que tem DONOS diferentes, somem."""
    p = build_verificar_par_prompt(AFIRMACAO, TRECHO_OK)
    for rotulo in VEREDITOS:
        assert f"`{rotulo}`" in p, f"rotulo {rotulo} nao esta declarado no prompt"
    assert "REFINAMENTO" in p and "RETRIEVAL" in p


def test_prompt_e_adversarial_e_proibe_esconder_divergencia_numerica():
    p = build_verificar_par_prompt(
        AFIRMACAO, TRECHO_DIGITO_TROCADO,
        numeros_divergentes=[{"na_afirmacao": "723.810.827,57",
                              "no_trecho": "723.910.827,57"}],
    )
    assert "POSTURA DEFAULT = REPROVAR" in p
    assert "NAO responda `supported`" in p
    assert "723.910.827,57" in p


def test_prompt_exige_confianca_em_campo_com_objeto():
    p = build_verificar_par_prompt(AFIRMACAO, TRECHO_OK)
    assert "objeto_da_confianca" in p
    assert "nunca prosa" in p
    # O objeto tem que ser NOMEADO — "85% de que li certo" e outra afirmacao.
    assert "SUSTENTA ESTA AFIRMACAO" in p


def test_ancora_nao_entra_no_prompt_mas_volta_na_resposta(monkeypatch):
    """A ancora e correlacao para o CHAMADOR, nao contexto de julgamento.

    doc_id e hash nao ajudam a julgar semantica e dariam ao cego exatamente a
    pista de proveniencia que o desenho lhe tira.
    """
    _dinco_off(monkeypatch)
    ancora = {"doc_id": "acordao.pdf", "sid": "fl5-s12", "pagina": 5,
              "doc_hash": "sha256:abc", "extractor_version": "pymupdf-1.24.9"}
    fake = _mock_provider(monkeypatch, _resposta())
    r = _rodar(verificar_par(_req(ancora=ancora)))
    assert r.success and r.ancora == ancora
    assert "acordao.pdf" not in fake.prompts[0]
    assert "fl5-s12" not in fake.prompts[0]


# ══ 2. Vocabulario fechado ══════════════════════════════════════════════════

@pytest.mark.parametrize("veredito", list(VEREDITOS))
def test_os_quatro_rotulos_sao_aceitos(monkeypatch, veredito):
    _dinco_off(monkeypatch)
    motivo = MOTIVO_OK if veredito == "supported" else "trecho_incompleto"
    _mock_provider(monkeypatch, _resposta(veredito, motivo))
    r = _rodar(verificar_par(_req()))
    assert r.success and r.veredito == veredito


@pytest.mark.parametrize("lixo", ["aprovado", "ok", True, "SUPPORTED", "grounded", None])
def test_rotulo_fora_do_vocabulario_reprova_a_resposta(monkeypatch, lixo):
    """Nao coagimos "aprovado" -> supported: coercao esconde um modelo que nao
    entendeu o contrato e vira aprovacao silenciosa."""
    _dinco_off(monkeypatch)
    _mock_provider(monkeypatch, json.dumps({
        "veredito": lixo, "motivo_tipado": MOTIVO_OK, "motivo": "",
        "confianca": 0.9, "objeto_da_confianca": "x",
    }))
    r = _rodar(verificar_par(_req()))
    assert not r.success
    assert r.error_tipo == "vocabulario"
    assert r.veredito is None


@pytest.mark.parametrize("motivo_tipado", list(MOTIVOS_TIPADOS))
def test_todos_os_motivos_do_enum_sao_aceitos(monkeypatch, motivo_tipado):
    _dinco_off(monkeypatch)
    _mock_provider(monkeypatch, _resposta("partial", motivo_tipado))
    r = _rodar(verificar_par(_req()))
    assert r.success and r.motivo_tipado == motivo_tipado


def test_motivo_tipado_em_prosa_reprova(monkeypatch):
    """Prosa aqui e o que impede o QA de agregar — o motivo LIVRE tem campo
    proprio (`motivo`)."""
    _dinco_off(monkeypatch)
    _mock_provider(monkeypatch, _resposta(
        "contradicted", "o trecho fala de outro periodo de apuracao"))
    r = _rodar(verificar_par(_req()))
    assert not r.success and r.error_tipo == "vocabulario"


def test_supported_e_o_unico_que_aceita_sem_divergencia(monkeypatch):
    """`partial` + `sem_divergencia` e incoerente: se nao ha o que apontar, o
    veredito e supported."""
    _dinco_off(monkeypatch)
    _mock_provider(monkeypatch, _resposta("partial", MOTIVO_OK))
    r = _rodar(verificar_par(_req()))
    assert not r.success and r.error_tipo == "vocabulario"


def test_parse_quebrado_nao_aprova_nada(monkeypatch):
    _dinco_off(monkeypatch)
    _mock_provider(monkeypatch, "isto nao e json")
    r = _rodar(verificar_par(_req()))
    assert not r.success and r.error_tipo == "parse" and r.veredito is None


# ══ 3. numeros_divergentes em CODIGO ════════════════════════════════════════

def test_numeros_divergentes_pega_digito_trocado():
    """723.910 x 723.810 — a mutacao classica do G2, agora contra o par."""
    div = _numeros_divergentes(AFIRMACAO, TRECHO_DIGITO_TROCADO)
    assert len(div) == 1
    assert div[0]["na_afirmacao"] == "723.810.827,57"
    assert div[0]["no_trecho"] == "723.910.827,57"


def test_numeros_divergentes_tolera_ocr_em_letra():
    """`723.81O` (letra O) canoniza para os mesmos digitos — NAO e divergencia.
    Regressao direta do gate G2: ruido de OCR em letra e tolerado, digito
    diferente nunca."""
    assert _numeros_divergentes(AFIRMACAO, TRECHO_OCR_LETRA) == []


def test_numeros_extras_no_trecho_nao_sao_divergencia():
    """A direcao e assimetrica de proposito: o trecho quase sempre traz numeros
    que a afirmacao nao cita (folha, artigo, percentual)."""
    trecho = (
        "Fls. 1042. Nos termos do art. 142 do CTN, mantem-se o IRPJ principal "
        "de R$ 723.810.827,57, com multa de oficio de 75%."
    )
    assert _numeros_divergentes(AFIRMACAO, trecho) == []


def test_numero_ausente_no_trecho_vira_divergencia_com_no_trecho_vazio():
    """"o trecho nao tem numero que corresponda" tambem e uma resposta."""
    div = _numeros_divergentes(AFIRMACAO, "O recurso foi conhecido e provido em parte.")
    assert len(div) == 1
    assert div[0]["na_afirmacao"] == "723.810.827,57"
    assert div[0]["no_trecho"] == ""


def test_divergencia_rebaixa_supported_do_modelo(monkeypatch):
    """A trava central: o modelo APROVA e o codigo REPROVA.

    Se esta protecao fosse instrucao de prompt, uma alucinacao numerica de alta
    confianca (risco nº 3 da pesquisa) passaria. Ela e codigo.
    """
    _dinco_off(monkeypatch)
    _mock_provider(monkeypatch, _resposta("supported", MOTIVO_OK))
    r = _rodar(verificar_par(_req(trecho=TRECHO_DIGITO_TROCADO)))

    assert r.success, "o rebaixamento e um veredito valido, nao um erro"
    assert r.veredito == "contradicted"
    assert r.motivo_tipado == "numero_diferente"
    assert r.numeros_divergentes and r.numeros_divergentes[0]["no_trecho"] == "723.910.827,57"
    assert "rebaixado por CODIGO" in r.motivo


def test_divergencia_nao_altera_veredito_ja_negativo(monkeypatch):
    """O rebaixamento so age sobre `supported` — nao sequestra o julgamento do
    modelo quando ele ja achou outra coisa (um `irrelevant` legitimo continua
    `irrelevant`, e a fila dele tem outro dono)."""
    _dinco_off(monkeypatch)
    _mock_provider(monkeypatch, _resposta("irrelevant", "trecho_nao_menciona"))
    r = _rodar(verificar_par(_req(trecho=TRECHO_DIGITO_TROCADO)))
    assert r.success and r.veredito == "irrelevant"
    assert r.motivo_tipado == "trecho_nao_menciona"
    assert r.numeros_divergentes, "a divergencia continua REPORTADA, so nao rebaixa"


def test_divergencias_vao_para_o_prompt_como_fato_dado(monkeypatch):
    """O LLM EXPLICA a divergencia; nao a redescobre (nem a discute)."""
    _dinco_off(monkeypatch)
    fake = _mock_provider(monkeypatch, _resposta("contradicted", "numero_diferente"))
    _rodar(verificar_par(_req(trecho=TRECHO_DIGITO_TROCADO)))
    assert "ACHOU divergencia" in fake.prompts[0]


def test_numeros_divergentes_reportados_mesmo_em_falha(monkeypatch):
    """O achado do codigo nao depende do LLM ter respondido bem."""
    _dinco_off(monkeypatch)
    _mock_provider(monkeypatch, "nao e json")
    r = _rodar(verificar_par(_req(trecho=TRECHO_DIGITO_TROCADO)))
    assert not r.success and r.numeros_divergentes


# ══ 3b. MESMA quantia, formas diferentes ════════════════════════════════════
#
# O bug que este bloco tranca: a canonizacao antiga tirava TODO nao-digito,
# entao o `.0` do repr de float do shared (`f"vale {valor!r}"`) virava digito.
# `500000.0` => "5000000" e `R$ 500.000,00` => "50000000" — nunca casavam, e
# TODO valor monetario CORRETO era reprovado como `numero_diferente`. A
# comparacao agora e por VALOR (Decimal), com a assinatura de digitos ainda na
# frente para o ruido de OCR em letra.

def test_float_do_shared_casa_com_moeda_brasileira():
    """(a) `500000.0` x `R$ 500.000,00` — a mesma quantia, nao divergencia.

    O caso EXATO que o motor produzia: o shared serializa o valor com `repr()`
    e o documento traz a forma brasileira.
    """
    assert _numeros_divergentes(
        "o valor da garantia e 500000.0",
        "consta apolice no valor de R$ 500.000,00.",
    ) == []


def test_float_com_centavos_casa_com_moeda_brasileira():
    """(b) `723810827.57` x `R$ 723.810.827,57` — milhar + decimal juntos."""
    assert _numeros_divergentes(
        "o IRPJ principal mantido e 723810827.57",
        "manter o IRPJ principal no valor de R$ 723.810.827,57.",
    ) == []


def test_quantia_diferente_continua_divergencia():
    """(c) `500000.0` x `R$ 600.000,00` — tolerar FORMA nao e tolerar VALOR.

    Se a normalizacao passasse a casar isto, o fix teria trocado o falso
    positivo por um falso NEGATIVO — e o falso negativo e o pior dos dois:
    numero errado aprovado em silencio.
    """
    div = _numeros_divergentes(
        "o valor da garantia e 500000.0",
        "consta apolice no valor de R$ 600.000,00.",
    )
    assert len(div) == 1
    assert div[0]["na_afirmacao"] == "500000.0"


def test_percentual_casa_com_o_numero_cru():
    """(d) `75` x `75%` — o `%` e unidade, nao digito."""
    assert _numeros_divergentes(
        "a multa de oficio aplicada foi de 75",
        "com multa de oficio de 75%.",
    ) == []


def test_ocr_em_letra_no_meio_nao_piora_com_a_camada_de_valor():
    """(e) `723.81O.827` (letra O) segue tolerado, e o veredito nao muda.

    A camada de valor e ADITIVA: ela so pode REMOVER divergencia falsa, nunca
    criar uma. Este e o teste do bloco 3 visto do outro lado — a garantia de
    que o fix nao mexeu no gate G2.
    """
    assert _numeros_divergentes(AFIRMACAO, TRECHO_OCR_LETRA) == []
    # e a mutacao de DIGITO continua pega, com o vizinho certo apontado
    div = _numeros_divergentes(AFIRMACAO, TRECHO_DIGITO_TROCADO)
    assert len(div) == 1 and div[0]["no_trecho"] == "723.910.827,57"


def test_ocr_em_letra_tambem_casa_atraves_das_formas():
    """OCR em letra E forma diferente ao mesmo tempo: `500000.0` x `R$ 5OO.OOO,OO`.

    Canonizar o OCR ANTES de parsear o valor e o que faz os dois defeitos
    somarem em vez de se cancelarem.
    """
    assert _numeros_divergentes(
        "o valor da garantia e 500000.0",
        "consta apolice no valor de R$ 5OO.OOO,OO.",
    ) == []


@pytest.mark.parametrize("literal,esperado", [
    ("500000.0", "500000"),        # sufixo .0 do repr de float
    ("500.000,00", "500000"),      # moeda brasileira
    ("1.234.567,89", "1234567.89"),  # BR: milhar `.` + decimal `,`
    ("1,234,567.89", "1234567.89"),  # US: milhar `,` + decimal `.`
    ("1,5", "1.5"),                # separador unico, 1 casa => decimal
    ("75", "75"),
])
def test_valores_candidatos_normaliza_as_formas(literal, esperado):
    """A quantia certa esta SEMPRE entre os candidatos do literal."""
    assert Decimal(esperado) in _valores_candidatos(literal)


def test_separador_unico_ambiguo_rende_as_duas_leituras():
    """`1.234` e mil-duzentos-e-trinta-e-quatro (BR) — 3 digitos e milhar.

    Ja `1,5` nao pode ser milhar (grupo de milhar tem 3 digitos), entao so
    rende a leitura decimal. Escolher UMA leitura para o caso ambiguo criaria
    falso positivo na outra.
    """
    assert Decimal("1234") in _valores_candidatos("1.234")
    assert _valores_candidatos("1,5") == {Decimal("1.5")}


# ══ 4. Envelope em CAMPO ════════════════════════════════════════════════════

def test_envelope_sem_objeto_faz_retry_que_nomeia_a_falha(monkeypatch):
    """Um retry, e o retry DIZ o que faltou — modelo costuma acertar quando lhe
    apontam o campo. Depois disso, erro; nunca um default (confianca inventada
    pelo codigo e o pior resultado possivel)."""
    ruim = json.dumps({
        "veredito": "supported", "motivo_tipado": MOTIVO_OK, "motivo": "ok",
        "confianca": 0.9,  # sem objeto_da_confianca
    })
    _dinco_off(monkeypatch)
    fake = _mock_provider(monkeypatch, [ruim, _resposta()])
    r = _rodar(verificar_par(_req()))

    assert fake.n_chamadas == 2, "faltou o retry"
    assert "CORRECAO OBRIGATORIA" in fake.prompts[1]
    assert "objeto_da_confianca" in fake.prompts[1]
    assert r.success and r.objeto_da_confianca


def test_envelope_invalido_duas_vezes_vira_erro_tipado(monkeypatch):
    ruim = json.dumps({
        "veredito": "supported", "motivo_tipado": MOTIVO_OK, "motivo": "ok",
        "confianca": 0.9,
    })
    _dinco_off(monkeypatch)
    fake = _mock_provider(monkeypatch, [ruim, ruim])
    r = _rodar(verificar_par(_req()))

    assert fake.n_chamadas == 2, "so UM retry — nao um loop de tentativas"
    assert not r.success and r.error_tipo == "envelope"
    assert r.confianca is None, "sem confianca valida, o campo fica VAZIO"


@pytest.mark.parametrize("prosa", ["alta", "85%", "0.85", None])
def test_confianca_em_prosa_e_rejeitada(monkeypatch, prosa):
    """"0.85" entre aspas nao e campo numerico. Confianca em prosa e o
    confidence laundering que o §5.3 existe pra matar."""
    ruim = json.dumps({
        "veredito": "supported", "motivo_tipado": MOTIVO_OK, "motivo": "ok",
        "confianca": prosa, "objeto_da_confianca": "de que sustenta",
    })
    _dinco_off(monkeypatch)
    _mock_provider(monkeypatch, [ruim, ruim])
    r = _rodar(verificar_par(_req()))
    assert not r.success and r.error_tipo == "envelope"


def test_custo_do_retry_e_somado(monkeypatch):
    """Retry que nao aparece no ledger e o mesmo modo de falha que escondeu
    US$ 97,61 em 39.309 calls."""
    ruim = json.dumps({"veredito": "supported", "motivo_tipado": MOTIVO_OK,
                       "motivo": "ok", "confianca": 0.9})
    _dinco_off(monkeypatch)
    _mock_provider(monkeypatch, [ruim, _resposta()], cost=0.002)
    r = _rodar(verificar_par(_req()))
    assert r.success and r.cost_usd == pytest.approx(0.004)


def test_par_incompleto_nem_chama_o_modelo(monkeypatch):
    _dinco_off(monkeypatch)
    fake = _mock_provider(monkeypatch, _resposta())
    r = _rodar(verificar_par(_req(trecho="   ")))
    assert not r.success and r.error_tipo == "request"
    assert fake.n_chamadas == 0


# ══ 5. DINCO ════════════════════════════════════════════════════════════════

def test_dinco_desligado_faz_uma_chamada_e_declara_n_igual_1(monkeypatch):
    """Desligado, N EFETIVO = 1 — e ele vai DECLARADO. Metrica de A/B sem o N
    gravado e incomparavel."""
    _dinco_off(monkeypatch)
    fake = _mock_provider(monkeypatch, _resposta())
    r = _rodar(verificar_par(_req()))

    assert fake.n_chamadas == 1
    assert r.self_consistency_n == 1 and r.dinco_enabled is False
    assert r.confianca == pytest.approx(0.88), "verbalizado CRU, sem normalizar"
    assert len(r.votos) == 1 and r.votos[0]["variante"] == "__alegacao__"


def test_dinco_ligado_faz_n_chamadas_independentes(monkeypatch):
    """N chamadas, e NENHUMA sabe das outras: e a independencia que remove a
    sugestionabilidade (se o modelo visse as variantes juntas, saberia qual e
    "a" alegacao e a confianca voltaria a saturar)."""
    monkeypatch.setenv("FICHAS_DINCO_ENABLED", "true")
    monkeypatch.setenv("SELF_CONSISTENCY_N", "3")
    voto = json.dumps({"confianca": 0.30, "objeto_da_confianca": "de que sustenta"})
    fake = _mock_provider(monkeypatch, [_resposta(), voto, voto])
    r = _rodar(verificar_par(_req()))

    assert r.success and r.dinco_enabled is True and r.self_consistency_n == 3
    assert fake.n_chamadas == 3, "1 julgamento + 2 distractors"
    for p in fake.prompts[1:]:
        assert "variante" not in p.lower(), "o voto nao pode saber que e variante"
        assert AFIRMACAO not in p, "o voto nao pode ver a alegacao original"


def test_dinco_normaliza_a_confianca_para_baixo(monkeypatch):
    """0,88 cru vira 0,88/(0,88+0,3+0,3) — e isso e o ponto: verbalizado cru
    satura em 0,9/0,95 e nao da limiar."""
    monkeypatch.setenv("FICHAS_DINCO_ENABLED", "1")
    monkeypatch.setenv("SELF_CONSISTENCY_N", "3")
    voto = json.dumps({"confianca": 0.30, "objeto_da_confianca": "de que sustenta"})
    _mock_provider(monkeypatch, [_resposta(), voto, voto])
    r = _rodar(verificar_par(_req()))

    assert r.confianca < 0.88, "confianca DINCO tem que ser menor que a crua"
    assert r.confianca == pytest.approx(0.88 / (0.88 + 0.30 + 0.30), abs=1e-3)


def test_dinco_grava_todos_os_votos(monkeypatch):
    """Sem os votos gravados nao ha recalibracao depois nem investigacao de uma
    celula que saiu errada — item 6 da lista do §5.1."""
    monkeypatch.setenv("FICHAS_DINCO_ENABLED", "on")
    monkeypatch.setenv("SELF_CONSISTENCY_N", "4")
    votos_txt = [
        json.dumps({"confianca": c, "objeto_da_confianca": "de que sustenta"})
        for c in (0.20, 0.35, 0.10)
    ]
    _mock_provider(monkeypatch, [_resposta(), *votos_txt],)
    r = _rodar(verificar_par(_req(distractors=[723811827.57, 723809827.57, 999.0])))

    assert r.self_consistency_n == 4
    assert len(r.votos) == 4, "a alegacao + os 3 distractors, TODOS gravados"
    assert r.votos[0]["variante"] == "__alegacao__"
    assert all("confianca" in v for v in r.votos)


def test_n_efetivo_e_o_real_nao_o_teto_pedido(monkeypatch):
    """`SELF_CONSISTENCY_N` e TETO, nao promessa.

    Um trecho com um unico numero so rende as duas perturbacoes de milhar — o
    `gerar_distractors` devolve 2 mesmo com N=4 pedido. Gravar 4 faria a
    recalibracao comparar DINCO@3 com DINCO@4 como iguais, que e exatamente o
    que o N gravado existe pra evitar.
    """
    monkeypatch.setenv("FICHAS_DINCO_ENABLED", "true")
    monkeypatch.setenv("SELF_CONSISTENCY_N", "4")
    voto = json.dumps({"confianca": 0.3, "objeto_da_confianca": "de que sustenta"})
    fake = _mock_provider(monkeypatch, [_resposta(), voto, voto, voto])
    r = _rodar(verificar_par(_req()))

    assert fake.n_chamadas == 3, "so ha 2 distractors plausiveis neste trecho"
    assert r.self_consistency_n == 3, "o N gravado e o EFETIVO"
    assert len(r.votos) == 3


def test_dinco_aceita_distractors_prontos_do_chamador(monkeypatch):
    """Quem tem o DocumentoIndexado gera distractors melhores que a heuristica
    local — o request aceita os dele."""
    monkeypatch.setenv("FICHAS_DINCO_ENABLED", "true")
    monkeypatch.setenv("SELF_CONSISTENCY_N", "3")
    voto = json.dumps({"confianca": 0.4, "objeto_da_confianca": "de que sustenta"})
    fake = _mock_provider(monkeypatch, [_resposta(), voto, voto])
    r = _rodar(verificar_par(_req(distractors=[999888777.11, 123456789.00])))

    assert r.success and len(r.votos) == 3
    assert "999888777.11" in fake.prompts[1] or "999888777.11" in fake.prompts[2]


def test_flag_off_ignora_n_dinco_do_request(monkeypatch):
    """Custo N-vezes maior nao entra pela porta do payload: a flag e o
    interruptor de producao, `n_dinco` e so o ajuste fino."""
    _dinco_off(monkeypatch)
    fake = _mock_provider(monkeypatch, _resposta())
    r = _rodar(verificar_par(_req(n_dinco=10)))
    assert fake.n_chamadas == 1 and r.self_consistency_n == 1


def test_n_igual_1_com_flag_ligada_desliga_o_dinco(monkeypatch):
    """N=1 e o A/B declarado contra a baseline (verbalizado cru)."""
    monkeypatch.setenv("FICHAS_DINCO_ENABLED", "true")
    fake = _mock_provider(monkeypatch, _resposta())
    r = _rodar(verificar_par(_req(n_dinco=1)))
    assert fake.n_chamadas == 1 and r.self_consistency_n == 1


def test_voto_com_envelope_invalido_e_descartado_nao_vira_zero(monkeypatch):
    """Zero inventado diminuiria o denominador e INFLARIA a confianca da
    alegacao — a direcao errada de errar."""
    monkeypatch.setenv("FICHAS_DINCO_ENABLED", "true")
    monkeypatch.setenv("SELF_CONSISTENCY_N", "3")
    bom = json.dumps({"confianca": 0.4, "objeto_da_confianca": "de que sustenta"})
    _mock_provider(monkeypatch, [_resposta(), bom, "lixo que nao parseia"])
    r = _rodar(verificar_par(_req()))

    assert r.success
    assert r.confianca == pytest.approx(0.88 / (0.88 + 0.40), abs=1e-3)


def test_valor_da_afirmacao_pega_o_monetario_e_nao_o_contexto():
    """O maior numero domina: artigo, folha e percentual sao contexto."""
    assert _valor_da_afirmacao(AFIRMACAO) == pytest.approx(723810827.57)
    assert _valor_da_afirmacao("competencia 2019-03 do IRPJ") == "2019-03"


# ══ 6. Modelo — anti-conluio ════════════════════════════════════════════════

def test_verificador_usa_modelo_diferente_do_calculador():
    """A premissa central do desenho: investigador != verificador. Auditar com
    o mesmo modelo que calculou e pedir que alguem revise o proprio trabalho —
    os erros sao correlacionados e se confirmam mutuamente."""
    from garantis_shared.llm_models import model_for
    assert model_for("ficha_auditoria_evidencias") != model_for("ficha_calculo")


def test_default_do_verificador_sai_do_papel_e_nao_de_literal(monkeypatch):
    """Literal duplicado envelhece calado — foi assim que o calculador ficou
    apontando para um modelo fora do catalogo (preco 0/0, custo invisivel)."""
    import importlib

    from garantis_shared.llm_models import model_for
    for var in ("AUDITOR_EVIDENCIAS_MODEL", "DEFAULT_MODEL"):
        monkeypatch.delenv(var, raising=False)
    try:
        recarregado = importlib.reload(verif_mod)
        assert recarregado.DEFAULT_MODEL == model_for("ficha_auditoria_evidencias")
    finally:
        monkeypatch.undo()
        importlib.reload(verif_mod)


def test_modelo_do_verificador_esta_no_catalogo_e_nao_e_preview():
    """Fora de `MODELS` o preco sai 0/0 e o gasto some do ledger EM SILENCIO —
    o mecanismo que ja escondeu US$ 97,61 em 39.309 calls. E `-preview` 404a no
    Vertex, que e o backend de todos os cloudbuilds da casa."""
    from garantis_shared.llm_models import MODELS, model_for

    modelo = model_for("ficha_auditoria_evidencias")
    assert modelo in MODELS, f"{modelo} fora do catalogo => preco 0/0 => custo invisivel"
    assert "preview" not in modelo, f"{modelo} e preview — 404 no Vertex"
    spec = MODELS[modelo]
    assert spec.input_usd_per_1m > 0 and spec.output_usd_per_1m > 0


# ══ 7. Rotas — a nova e a COMPAT da antiga ══════════════════════════════════

@pytest.fixture()
def client() -> TestClient:
    from src.api.routes.verificador import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_rota_verificar_par(client, monkeypatch):
    _dinco_off(monkeypatch)
    _mock_provider(monkeypatch, _resposta("partial", "trecho_incompleto"))
    resp = client.post("/calculo-ficha/verificar-par", json=_req())

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] and body["veredito"] == "partial"
    assert body["motivo_tipado"] == "trecho_incompleto"
    # Envelope da casa + os campos do contrato do §2.3.
    assert {"success", "model", "cost_usd", "confianca", "objeto_da_confianca",
            "numeros_divergentes", "votos", "self_consistency_n"} <= set(body)


def test_rota_devolve_200_em_falha_de_validacao(client, monkeypatch):
    """`success=false` com HTTP 200 — o harness decide a rodada. 500 fica so
    para falha inesperada de infraestrutura."""
    _dinco_off(monkeypatch)
    _mock_provider(monkeypatch, "nao e json")
    resp = client.post("/calculo-ficha/verificar-par", json=_req())
    assert resp.status_code == 200 and resp.json()["success"] is False


def test_rota_nova_registrada_no_app_principal():
    """Rota escrita mas nao registrada = 404 em producao (foi o bloqueador B1
    do write-fields)."""
    from src.api.main import app
    caminhos = set(app.openapi()["paths"])
    assert "/calculo-ficha/verificar-par" in caminhos


def test_compat_rota_antiga_continua_registrada():
    """O modo cego e ADITIVO. O harness do shared chama `/auditar-evidencias`
    HOJE — quebrar isso quebra a producao, e a rota so morre na onda 6."""
    from src.api.main import app
    caminhos = set(app.openapi()["paths"])
    assert "/calculo-ficha/auditar-evidencias" in caminhos
    assert "/calculo-ficha/montar-grafo" in caminhos


def test_compat_contrato_do_auditor_antigo_intacto(monkeypatch):
    """O contrato `{veredictos: [{celula_id, aprovada, motivo}], model,
    cost_usd}` continua byte-compativel."""
    fake = _FakeProvider(json.dumps({"veredictos": [
        {"celula_id": "irpj_principal", "aprovada": False,
         "motivo": "o trecho cita a base de calculo, nao o credito tributario"},
    ]}))
    monkeypatch.setattr(auditor_mod, "create_provider", lambda *_a, **_k: fake)
    r = _rodar(auditar_evidencias({
        "celulas": [{"id": "irpj_principal", "tipo": "dado", "valor": 723810827.57}],
        "evidencias": [{"celula_id": "irpj_principal", "documento": "acordao.pdf",
                        "trecho": TRECHO_OK}],
        "documentos": {"acordao.pdf": TRECHO_OK},
    }))

    assert r.success
    assert set(r.veredictos[0]) == {"celula_id", "aprovada", "motivo"}
    assert r.veredictos[0]["aprovada"] is False
    assert isinstance(r.model, str) and isinstance(r.cost_usd, float)


def test_os_dois_modos_convivem_no_mesmo_pacote():
    """Importar um nao pode quebrar o outro — e o `verificar_par` nao pode ter
    virado um alias do modo antigo."""
    from src.agents.auditor_evidencias import auditar_evidencias as a
    from src.agents.auditor_evidencias import verificar_par as v
    assert a is not v
    assert a.__module__.endswith(".agent")
    assert v.__module__.endswith(".verificador")

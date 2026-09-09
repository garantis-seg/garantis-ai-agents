"""O C5 -- a ROTA `POST /mov-factsheet/confirmar-peticao`, com provider duble.

⛔ **Nenhum teste aqui exercita so a funcao pura.** A licao catalogada da casa e
que *"funcao pura nao cobre o VARREDOR/LOADER"*: o defeito que este pacote existe
pra evitar (o frame virar indutor) atravessa request -> schema -> prompt -> params
do provider, e um teste de `build_confirmador_prompt` isolado passaria verde com a
rota devolvendo outra coisa. Tudo abaixo passa pelo `TestClient`, menos os guards
de TEXTO -- que sao sobre o arquivo, nao sobre a chamada.

O que cada bloco trava:

  1. VERBATIM       -- sha256 de `SISTEMA`/`USUARIO`/`BLOCO`. Qualquer edicao do
                       texto medido fica VERMELHA. E a friccao e o ponto: quem
                       reescrever tem de encarar que a medicao (21/22 x 1/22,
                       Fisher p = 2,19e-11) deixou de descrever o que roda.
  2. OS 4 INVARIANTES -- frase-ancora por invariante. Sobrevive a uma re-medicao
                       aprovada (onde o hash seria bumpado) e continua exigindo
                       que o FRAME esteja la.
  3. VAZAMENTO      -- metadado que permite decidir SEM LER nao chega ao prompt.
  4. CONTRATO       -- `escolhido` INDICE 0..N, `continuacao`, card integro.
  5. PARAMETROS     -- os medidos: modelo, temp 0, top_p 1, top_k 1, thinking 0,
                       `response_schema` estruturado, `system_instruction`.
  6. FALHA          -- parse quebrado vira 500, ⛔ NUNCA `escolhido=0`.
  7. REGISTRO       -- a rota existe no app principal (rota nao registrada = 404
                       em producao = o C5 segue inerte, que e o defeito de hoje).
"""
from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import src.agents.peticao_confirmador.agent as agent_mod
from src.agents.peticao_confirmador.prompts import BLOCO, SISTEMA, USUARIO

# ── duble ───────────────────────────────────────────────────────────────────


class _FakeProvider:
    """Provider duble: devolve textos em fila e grava TODOS os kwargs recebidos.

    Grava os kwargs (nao so o prompt) porque metade do que este pacote compra sao
    PARAMETROS medidos -- modelo, temperatura, janela de decodificacao, o
    `response_schema` estruturado e o `system_instruction`.
    """

    def __init__(self, textos, cost: float = 0.0001):
        self._textos = [textos] if isinstance(textos, str) else list(textos)
        self._i = 0
        self._cost = cost
        self.chamadas: list[dict] = []

    async def agenerate(self, **kwargs):
        self.chamadas.append(kwargs)
        texto = self._textos[min(self._i, len(self._textos) - 1)]
        self._i += 1
        return SimpleNamespace(
            text=texto, model=kwargs.get("model"),
            input_tokens=4200, output_tokens=120, cached_tokens=0,
            metadata={"cost_usd": self._cost, "provider": "gemini"},
        )

    @property
    def n_chamadas(self) -> int:
        return len(self.chamadas)


def _mock_provider(monkeypatch, textos, **kw) -> _FakeProvider:
    fake = _FakeProvider(textos, **kw)
    monkeypatch.setattr(agent_mod, "create_provider", lambda *_a, **_k: fake)
    return fake


def _veredito(escolhido=1, continuacao=(), motivo="a peca abre enderecando o juizo") -> str:
    return json.dumps({"escolhido": escolhido, "continuacao": list(continuacao),
                       "motivo": motivo})


# ── fixtures do dominio ─────────────────────────────────────────────────────

#: Metadado que o payload TRAZ (vem do mesmo loader do L1-mov) e que ⛔ NAO pode
#: chegar ao prompt. `data_documento` nao esta no contrato de proposito -- entra
#: aqui como campo EXTRA pra provar que nem por acidente ele passaria.
#:
#: ⚠️ Os valores sao SENTINELAS, e isso e deliberado: na vida real o `nm_tomador` e
#: quase sempre IGUAL a um dos polos, que entram no prompt legitimamente. Repetir o
#: polo aqui faria o teste falhar por coincidencia de string e nao mediria o que
#: promete -- se o CAMPO foi injetado. Valor distinto e a unica forma de o assert
#: falar do campo, e nao do texto.
PROIBIDOS = {
    "materia": "tributario",
    "nm_tomador": "SENTINELA TOMADOR NAO DEVE APARECER",
    "cnpj_tomador": "12345678000199",
    "classe_cnj_code": 1116,
}

HEAD_1 = ("EXCELENTISSIMO SENHOR DOUTOR JUIZ DE DIREITO DA 3a VARA DE EXECUCOES "
          "FISCAIS. A UNIAO propoe a presente execucao fiscal em face de ACME.")
HEAD_2 = "Certifico que a publicacao ocorreu no DJe de folha 12, do que dou fe."
HEAD_3 = "(continuacao) ... e, ao final, requer a procedencia, pede deferimento."


def _req(**over) -> dict:
    base = {
        "processo": {
            "cnj": "0001234-56.2020.4.02.5101",
            "classe": "Execucao Fiscal",
            "tribunal": "TRF2",
            "assunto": "IRPJ",
            "polo_ativo": "UNIAO FEDERAL",
            "polo_passivo": "ACME PARTICIPACOES LTDA",
            **PROIBIDOS,
        },
        "head_chars": 3000,
        "candidatos": [
            {"n": 1, "doc_key": "jb-99887766", "titulo": "PETICAO", "head": HEAD_1},
            {"n": 2, "doc_key": "esc-11223344", "titulo": "CERTIDAO", "head": HEAD_2},
            {"n": 3, "doc_key": "jb-55443322", "titulo": "DOC 02", "head": HEAD_3},
        ],
    }
    base.update(over)
    return base


@pytest.fixture()
def client() -> TestClient:
    from src.api.routes.mov_factsheet import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


ROTA = "/mov-factsheet/confirmar-peticao"


# ══ 1. VERBATIM ═════════════════════════════════════════════════════════════

#: sha256 do texto EXATO com que a camada foi medida (arnes `d2_prompt.py`,
#: 08-09/09/2026). ⛔ Bumpar isto sem re-rodar o gold N=22 E os DOIS controles
#: negativos e trocar a medicao por uma opiniao.
_SHA_MEDIDO = {
    "SISTEMA": "ec94a53162a39340fafa79a40bcc964816621d54f39fb3c6e5d22aa7faeb87b6",
    "USUARIO": "3d5844625d5933c39426826ba53485672dd81b950fd4d3563a7a3faf864f7d0d",
    "BLOCO": "3743e5690219b378bf63796b8826962f096d3af97c4136b6e2a8def8845a1ef1",
}


@pytest.mark.parametrize("nome,texto", [
    ("SISTEMA", SISTEMA), ("USUARIO", USUARIO), ("BLOCO", BLOCO),
])
def test_o_texto_do_prompt_e_o_texto_MEDIDO(nome, texto):
    """O placar 21/22 x 1/22 foi medido com ESTE texto, byte a byte.

    Reescrever, traduzir, acentuar ou "enxugar" devolve esta camada ao C4 com outro
    nome -- e o C4 afirmava `peticao_inicial` em 49,2% de 4.228 chamadas quando a
    verdade e ~3%. O hash existe pra que isso seja um teste vermelho, nao uma
    descoberta em producao.
    """
    assert hashlib.sha256(texto.encode("utf-8")).hexdigest() == _SHA_MEDIDO[nome], (
        f"{nome} mudou -- a medicao do C5 ja nao descreve o que roda"
    )


# ══ 2. OS 4 INVARIANTES ═════════════════════════════════════════════════════

#: Uma frase-ancora por invariante, do texto que o `garantis_shared` audita.
_INVARIANTES = {
    "1-COMPARATIVO": ("Escolha entre os candidatos [1] a [{n}], ou 0 para NENHUM.",
                      USUARIO),
    "2-ABSTENCAO": ('Responder "nenhum" (escolhido = 0) e uma resposta CERTA e '
                    "esperada, nao uma", SISTEMA),
    "3-TEXTO": ("Decida pelo TEXTO, nao pelo titulo.", SISTEMA),
    "4-OUTRO-PROCESSO": ("essas copias comecam com a inicial DAQUELE processo.",
                         SISTEMA),
}


@pytest.mark.parametrize("invariante", sorted(_INVARIANTES))
def test_os_4_invariantes_estao_no_texto(invariante):
    """⛔ Ligar o endpoint sem os 4 e reabrir o C4 com outro nome.

    O `garantis_shared` os lista num comentario e o PR foi auditado contra eles; esta
    e a metade do contrato que vive DESTE lado, e nada no outro repo pode garanti-la.
    """
    frase, fonte = _INVARIANTES[invariante]
    assert frase in fonte, f"invariante {invariante} sumiu do prompt"


def test_a_abstencao_nao_tem_premio_nem_penalidade():
    """O invariante 2 e mais que a palavra "0": e a AUSENCIA de incentivo.

    Sem estas duas frases o modelo trata abster como falha e volta a escolher sempre
    -- que e exatamente o comportamento do frame indutor.
    """
    # ⚠️ As ancoras carregam a QUEBRA DE LINHA do texto medido de proposito: casar
    # "a frase" re-digitada em uma linha so passaria verde num prompt re-quebrado
    # (= outro texto = outra medicao).
    assert "Nao existe premio por\nescolher, nem penalidade por se abster." in SISTEMA
    assert "Apontar o documento errado e pior do que\nnao apontar nenhum." in SISTEMA


def test_o_frame_e_comparativo_no_fio(client, monkeypatch):
    """UMA chamada com os N candidatos JUNTOS -- ⛔ nunca N chamadas de 1 doc.

    O frame indutor esta medido em 4.228 chamadas de producao e e a maquina que
    fabricou os 411 cards errados. Um refactor que "paraleliza por documento" passa
    em todo teste de conteudo e reabre o incidente; este pega.
    """
    fake = _mock_provider(monkeypatch, _veredito(1))
    resp = client.post(ROTA, json=_req())

    assert resp.status_code == 200
    assert fake.n_chamadas == 1, "o frame COMPARATIVO e UMA chamada, nao N"
    prompt = fake.chamadas[0]["prompt"]
    for i, head in enumerate((HEAD_1, HEAD_2, HEAD_3), 1):
        assert f"----- CANDIDATO [{i}]" in prompt
        assert head in prompt
    assert "Escolha entre os candidatos [1] a [3], ou 0 para NENHUM." in prompt


# ══ 3. VAZAMENTO ════════════════════════════════════════════════════════════

def test_o_payload_nao_vaza_metadado_pro_prompt(client, monkeypatch):
    """⛔ Nenhum metadado que permita decidir SEM LER.

    `materia`/`nm_tomador`/`cnpj_tomador`/`classe_cnj_code` chegam no payload porque
    vem do mesmo loader do L1-mov; ⛔ nao entram no prompt, porque numero medido so
    descreve o payload medido. E o `doc_key` e identidade OPACA -- serve pro log
    deste agent, nao pra julgar.
    """
    _mock_provider(monkeypatch, _veredito(1))
    body = client.post(ROTA, json=_req()).json()
    prompt = body["llm_raw_prompt"]

    for campo, valor in PROIBIDOS.items():
        assert str(valor) not in prompt, f"{campo}={valor} vazou pro prompt"
    for chave in ("jb-99887766", "esc-11223344", "jb-55443322"):
        assert chave not in prompt, f"doc_key {chave} vazou pro prompt"


def test_campo_de_DATA_nao_chega_ao_prompt_nem_como_extra(client, monkeypatch):
    """🚨 A DATA e o caso NOMEADO, e ela foi tirada do payload por review.

    *"a inicial e a mais antiga"* e a heuristica que o degrau X1 ja aplica sozinho e
    de graca; oferece-la ao modelo lhe da como responder SEM ler -- e essa e a
    diferenca entre o frame comparativo e o indutor. Aqui ela entra como campo EXTRA
    do request pra provar que nem por acidente ela passa.
    """
    payload = _req()
    payload["processo"]["data_distribuicao"] = "2019-03-14"
    for c in payload["candidatos"]:
        c["data_documento"] = "2019-03-14"

    _mock_provider(monkeypatch, _veredito(1))
    body = client.post(ROTA, json=payload).json()
    assert "2019-03-14" not in body["llm_raw_prompt"]
    assert "data_documento" not in body["llm_raw_prompt"]


def test_llm_raw_prompt_carrega_as_DUAS_metades_do_frame(client, monkeypatch):
    """O guard de vazamento so vale se o campo auditado for o texto INTEIRO.

    Metade do frame (os invariantes 2/3/4) mora no `system_instruction`. Se
    `llm_raw_prompt` fosse so o `contents`, um vazamento na persona passaria batido e
    quem debuga veria meia chamada.
    """
    _mock_provider(monkeypatch, _veredito(0))
    body = client.post(ROTA, json=_req()).json()
    assert SISTEMA in body["llm_raw_prompt"]
    assert "----- CANDIDATO [1]" in body["llm_raw_prompt"]


def test_o_head_e_cortado_na_janela_DECLARADA_pelo_caller(client, monkeypatch):
    """A janela e a defesa ESTRUTURAL contra copia-integral, e o dono dela e o caller.

    O unico falso-positivo do gold **e** do acervo e o mesmo documento: um volume
    "Copia integral do MS n. <OUTRO processo>" cujo enderecamento da inicial DAQUELE
    processo comeca no char 3.914. ⛔ Este lado nao pode ter literal proprio -- ele
    corta no que o request DECLARA, senao viram duas fontes de verdade a divergir.
    """
    payload = _req(head_chars=50)
    payload["candidatos"] = [{"n": 1, "doc_key": "k", "titulo": "T",
                              "head": "A" * 40 + "SEGREDO_ALEM_DA_JANELA" + "B" * 200}]
    fake = _mock_provider(monkeypatch, _veredito(0))
    client.post(ROTA, json=payload)

    prompt = fake.chamadas[0]["prompt"]
    assert "SEGREDO_ALEM_DA_JANELA" not in prompt
    assert "A" * 40 in prompt


# ══ 4. CONTRATO ═════════════════════════════════════════════════════════════

def test_abstencao_sai_integra(client, monkeypatch):
    """`escolhido = 0` e resposta CERTA -- ⛔ nao e erro e nao vira 500."""
    _mock_provider(monkeypatch, _veredito(0, (), "nenhum trecho enderecca o juizo"))
    resp = client.post(ROTA, json=_req())

    assert resp.status_code == 200
    card = resp.json()["card"]
    assert card == {"escolhido": 0, "continuacao": [],
                    "motivo": "nenhum trecho enderecca o juizo"}


def test_escolha_com_continuacao_sai_integra(client, monkeypatch):
    """A peca partida em 2 documentos: escolhido = onde ela COMECA, resto em
    `continuacao`, na ordem de leitura."""
    _mock_provider(monkeypatch, _veredito(2, (3,), "parte 1 abre e interrompe"))
    resp = client.post(ROTA, json=_req())

    assert resp.status_code == 200
    card = resp.json()["card"]
    assert card["escolhido"] == 2
    assert card["continuacao"] == [3]
    assert card["motivo"] == "parte 1 abre e interrompe"


def test_escolhido_fora_de_faixa_passa_CRU_para_o_caller(client, monkeypatch):
    """⛔ Este lado NAO revalida e NAO coage.

    O `_valida_veredito` do `garantis_shared` transforma indice inexistente em
    ABSTENCAO. Clampar aqui criaria um segundo dono da regra e -- pior -- um
    `escolhido=99` viraria `3` em silencio, que e afirmar sobre o documento errado.
    """
    _mock_provider(monkeypatch, _veredito(99))
    body = client.post(ROTA, json=_req()).json()
    assert body["card"]["escolhido"] == 99


@pytest.mark.parametrize("lixo", [True, False, "2", 2.0, None])
def test_escolhido_fora_do_TIPO_nao_e_coagido_a_indice(client, monkeypatch, lixo):
    """🚨🚨 O caso mais silencioso do pacote: `true` virando "o candidato 1".

    O `_valida_veredito` do `garantis_shared` checa `isinstance(e, bool)` de
    proposito -- `bool` e subclasse de `int` em Python. ⛔ Mas a coercao LAX do
    Pydantic acontece ANTES de o payload sair daqui (`True -> 1`, `"2" -> 2`,
    `2.0 -> 2`), e entregaria um `1` limpo do outro lado: a guarda de la ficaria
    INALCANCAVEL e "o modelo dizendo sim" viraria uma afirmacao sobre o 1o
    documento. Sem este teste, o `strict=True` sai num refactor e ninguem ve.

    ⭐ A direcao certa e 500 -> `decidiu=False` -> ABSTENCAO: na duvida nao se afirma.
    """
    _mock_provider(monkeypatch, json.dumps(
        {"escolhido": lixo, "continuacao": [], "motivo": "x"}))
    resp = client.post(ROTA, json=_req())
    assert resp.status_code == 500, f"escolhido={lixo!r} foi COAGIDO a um indice"


def test_continuacao_com_bool_tambem_nao_e_coagida(client, monkeypatch):
    """Mesmo mecanismo, mesmo estrago: `[true]` viraria `[1]` e o caller
    concatenaria o candidato 1 como se fosse a "parte 2" da peca."""
    _mock_provider(monkeypatch, json.dumps(
        {"escolhido": 2, "continuacao": [True], "motivo": "x"}))
    assert client.post(ROTA, json=_req()).status_code == 500


def test_a_resposta_traz_prompt_version_e_usage(client, monkeypatch):
    """O caller le `prompt_version`, `usage["cost_usd"]` e `usage["model"]`.

    ⭐ `cost_usd` existe pra o contador da lane nao mentir na direcao CALMA: uma
    passada que PAGA e reporta 0.0 faz quem auditar a lane pelo contador dela ver
    ZERO com o fluxo pagando.
    """
    _mock_provider(monkeypatch, _veredito(1), cost=0.00042)
    body = client.post(ROTA, json=_req()).json()

    assert body["prompt_version"].startswith("peticao_confirmador.v1+")
    usage = body["usage"]
    assert usage["cost_usd"] == pytest.approx(0.00042)
    assert usage["model"] == "gemini-3.1-flash-lite"
    assert usage["total_tokens"] == 4200 + 120


# ══ 5. PARAMETROS MEDIDOS ═══════════════════════════════════════════════════

def test_os_parametros_da_chamada_sao_os_MEDIDOS(client, monkeypatch):
    """Determinismo medido 12/12 com prompt byte-identico, em `3.1-flash-lite`.

    ⛔ `gemini-3.1-flash` NAO-lite nao existe no Vertex (404). O `thinking_budget=0`
    e o mesmo regime do L1 de extracao (43/43 campos identicos com e sem thinking).
    """
    fake = _mock_provider(monkeypatch, _veredito(1))
    client.post(ROTA, json=_req())

    kw = fake.chamadas[0]
    assert kw["model"] == "gemini-3.1-flash-lite"
    assert kw["temperature"] == 0.0
    assert kw["top_p"] == 1.0
    assert kw["top_k"] == 1
    assert kw["thinking_budget"] == 0
    assert kw["max_tokens"] == 2048


def test_a_persona_vai_como_system_instruction(client, monkeypatch):
    """O arnes que mediu mandou `SISTEMA` como `system_instruction` e os candidatos
    como `contents` -- concatenar as duas metades num `prompt` so mudaria a chamada
    em relacao ao que foi medido."""
    fake = _mock_provider(monkeypatch, _veredito(1))
    client.post(ROTA, json=_req())

    kw = fake.chamadas[0]
    assert kw["system_instruction"] == SISTEMA
    assert kw["prompt"].startswith("PROCESSO")
    assert SISTEMA not in kw["prompt"], "a persona nao vai DUPLICADA no contents"


def test_o_veredito_vem_de_structured_output_e_nao_de_prosa(client, monkeypatch):
    """⛔ `response_schema` do provider, NUNCA parse de prosa -- e o schema e o dict
    VERBATIM do arnes, nao um JSON Schema gerado por Pydantic (que difere)."""
    from src.agents.peticao_confirmador.schemas import CONFIRMADOR_RESPONSE_SCHEMA

    fake = _mock_provider(monkeypatch, _veredito(1))
    client.post(ROTA, json=_req())

    schema = fake.chamadas[0]["response_schema"]
    assert schema is CONFIRMADOR_RESPONSE_SCHEMA
    assert schema["required"] == ["escolhido", "continuacao", "motivo"]
    assert schema["properties"]["escolhido"]["type"] == "integer"
    assert schema["properties"]["continuacao"]["items"]["type"] == "integer"


def test_o_provider_encaminha_system_instruction_pro_config():
    """O passthrough e ADITIVO: sem o kwarg, nada muda pra caller nenhum.

    Sem esta metade, o `system_instruction` do agent seria descartado em SILENCIO
    pelo `_build_config_params` e a chamada deixaria de ser a medida -- verde nos
    testes do agent, diferente no fio.
    """
    import os as _os

    _os.environ.setdefault("GEMINI_API_KEY", "dummy-test-key")
    from src.providers.gemini import GeminiProvider

    class _Types:
        class GenerateContentConfig:
            def __init__(self, **kw):
                self.kw = kw

        class ThinkingConfig:
            def __init__(self, **kw):
                self.kw = kw

    p = GeminiProvider.__new__(GeminiProvider)
    p._types = _Types
    p._default_model = "gemini-3.1-flash-lite"

    com = p._build_config_params(temperature=0.0, max_tokens=2048,
                                 response_schema=None, model="gemini-3.1-flash-lite",
                                 system_instruction="PERSONA")
    assert com["system_instruction"] == "PERSONA"

    sem = p._build_config_params(temperature=0.0, max_tokens=2048,
                                 response_schema=None, model="gemini-3.1-flash-lite")
    assert "system_instruction" not in sem


def test_o_modelo_esta_no_catalogo_e_nao_e_preview():
    """Fora de `MODELS` o preco sai 0/0 e o gasto some do ledger EM SILENCIO -- o
    mecanismo que ja escondeu US$ 97,61 em 39.309 calls. E `-preview` 404a no
    Vertex, backend de todos os cloudbuilds da casa."""
    from garantis_shared.llm_models import MODELS

    modelo = agent_mod.DEFAULT_MODEL
    assert modelo in MODELS, f"{modelo} fora do catalogo => preco 0/0 => custo invisivel"
    assert "preview" not in modelo
    spec = MODELS[modelo]
    assert spec.input_usd_per_1m > 0 and spec.output_usd_per_1m > 0


# ══ 6. FALHA ════════════════════════════════════════════════════════════════

def test_card_quebrado_vira_500_e_NUNCA_abstencao(client, monkeypatch):
    """🚨 A direcao do erro importa mais que o erro.

    Devolver `escolhido=0` num parse quebrado tornaria a falha indistinguivel de uma
    abstencao legitima, e o caller carimbaria (`decidiu=True`) o pn numa abstencao
    que NUNCA foi tomada -- congelando-o. O 500 chega la como `decidiu=False`: o pn
    fica onde esta e volta na proxima passada.
    """
    _mock_provider(monkeypatch, "isto nao e json")
    resp = client.post(ROTA, json=_req())

    assert resp.status_code == 500
    assert "escolhido" not in resp.text or "LLM parse error" in resp.text


def test_pool_vazio_nao_inventa_candidato(client, monkeypatch):
    """N=0: nao ha o que escolher, e o unico veredito possivel e 0."""
    fake = _mock_provider(monkeypatch, _veredito(0))
    resp = client.post(ROTA, json=_req(candidatos=[]))

    assert resp.status_code == 200
    assert resp.json()["card"]["escolhido"] == 0
    assert "Escolha entre os candidatos [1] a [0]" in fake.chamadas[0]["prompt"]


# ══ 7. REGISTRO ═════════════════════════════════════════════════════════════

def test_a_rota_esta_registrada_no_app_principal():
    """🚨 O DEFEITO QUE ESTE PR CONSERTA E EXATAMENTE ESTE.

    A rota ausente responde 404, que e `non_retryable` no `call` do
    `garantis_shared` -- devolve `None` sem abrir o circuito ⇒ o C5 ABSTEM em 100%
    dos pns ⇒ camada INERTE, em silencio. Rota escrita mas nao registrada tem o
    mesmo efeito.
    """
    from src.api.main import app
    caminhos = set(app.openapi()["paths"])
    assert ROTA in caminhos
    # as irmas continuam de pe -- o C5 e ADITIVO
    assert "/mov-factsheet/classify" in caminhos
    assert "/mov-factsheet/triage" in caminhos

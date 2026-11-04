"""R11: a fase A do redator v5 com function calling nativo, atrás de `FICHA_FASE_A_NATIVA`.

A casa decidiu MEDIR antes de trocar o protocolo. Este arquivo cobra que os 2 modos
sejam comparáveis e que o modo texto não mude com a flag desligada:

1. Flag desligada: nenhuma chamada da fase A leva `tools`, o prompt é o do texto, e a
   resposta diz `fase_a_metricas.modo == "texto"`.
2. Flag ligada: a fase A leva as 4 declarações e `tool_config` no modo ANY, executa a
   ferramenta, termina com `terminar_leitura`, e a fase B não muda.
3. Budget (25 por ficha, 5 por documento), circuit breaker e validação dos argumentos
   são os mesmos nos 2 modos.
4. Turno sem chamada válida conta em `invalidas` e, com 3 seguidos, encerra a fase A.
5. O provider monta `Tool`, `FunctionDeclaration` e `ToolConfig` do SDK, e devolve
   `metadata["function_calls"]`.
6. Gate de fonte: o turno de decisão do texto chama `parse_chamada` e não leva `tools`.
   Controle positivo: um trecho plantado com `tools=` é pego.
7. O auditor v3 continua no texto, mesmo com a flag ligada.

Sem rede e sem LLM: o provider é um dublê.
"""
from __future__ import annotations

import ast
import inspect
import json
from types import SimpleNamespace

import pytest
from google.genai import types as gtypes

import src.agents.ficha_writer.ferramentas as ferr_mod
from src.agents.ficha_writer import fase_a_nativa as N
from src.agents.ficha_writer.prompts_v5 import build_prompt_navegacao
from src.agents.ficha_writer.schemas import FichaWriteFieldsRequest
from src.agents.qualificador_conexo.ferramentas import FERRAMENTAS
from tests import test_ficha_writer_v5 as T

_NOMES = set(FERRAMENTAS) | {N.FERRAMENTA_FIM}


# ── Dublês ──────────────────────────────────────────────────────────────────


def _fc(name: str, **args) -> dict:
    """Uma chamada de função como o provider a devolve em `metadata["function_calls"]`."""
    return {"name": name, "args": args}


def _ler(doc_id: str = "carf:recurso.pdf") -> dict:
    return _fc("perguntar_ao_documento", doc_id=doc_id, pergunta="o REsp foi admitido?",
               slot="bullets[0]")


_FIM = _fc(N.FERRAMENTA_FIM)


class _ProvNativo(T._Prov):
    """Fase A com `tools`: devolve `function_calls` no metadata. Um item `str` da
    lista de decisões é texto sem função (turno inválido). Fase B igual ao dublê v5."""

    async def agenerate(self, **kw):
        if "tools" not in kw:
            return await super().agenerate(**kw)
        kw["_fase"] = "A"
        self.chamadas.append(kw)
        i = self.n["A"]
        self.n["A"] += 1
        item = (self.decisoes(i) if callable(self.decisoes)
                else self.decisoes[min(i, len(self.decisoes) - 1)])
        if isinstance(item, str):
            return SimpleNamespace(text=item, model=kw["model"],
                                   metadata={"cost_usd": 0.001, "function_calls": []})
        calls = item if isinstance(item, list) else [item]
        return SimpleNamespace(text="", model=kw["model"],
                               metadata={"cost_usd": 0.001, "function_calls": calls})


@pytest.fixture
def ligada(monkeypatch):
    monkeypatch.setenv(N.FLAG, "true")


@pytest.fixture
def desligada(monkeypatch):
    monkeypatch.delenv(N.FLAG, raising=False)


def _fase_a(prov) -> list[dict]:
    return [c for c in prov.chamadas if c["_fase"] == "A"]


# ── 1. flag desligada: o texto não muda ─────────────────────────────────────


def test_1_flag_desligada_e_o_protocolo_em_texto(desligada, monkeypatch):
    prov = T._Prov(T._leituras(), [T._emissao()])
    r = T._rodar(prov, monkeypatch)
    assert r.success, r.erros
    a = _fase_a(prov)
    assert len(a) == 3
    for c in a:
        assert "tools" not in c and "tool_config" not in c
        assert "Responda SÓ com um JSON" in c["prompt"]
        assert '{"fim": true}' in c["prompt"]
        assert N.FERRAMENTA_FIM not in c["prompt"]
    assert r.fase_a_metricas is not None
    assert r.fase_a_metricas.model_dump() == {
        "modo": "texto", "chamadas": 3, "invalidas": 0,
        "custo_usd": r.fase_a_metricas.custo_usd,
    }
    assert r.fase_a_metricas.custo_usd == pytest.approx(0.003 + 0.002, abs=1e-9)


def test_1b_o_prompt_do_texto_e_o_mesmo_com_e_sem_o_kwarg(desligada):
    req = FichaWriteFieldsRequest(**T._body())
    autos = ferr_mod.Autos(req.nucleo, req.indice_navegavel)
    kw = dict(chave="nova_apolice:carf", slots=[], citaveis=[], nucleo=autos.nucleo_para_llm(),
              indice=autos.indice_para_llm(), achados=[], menu=list(FERRAMENTAS),
              budget_restante=25, budget_por_doc=5, fence_token="T")
    padrao = build_prompt_navegacao(req, **kw)
    assert padrao == build_prompt_navegacao(req, nativo=False, **kw)
    nativo = build_prompt_navegacao(req, nativo=True, **kw)
    assert nativo != padrao
    # só o bloco <ferramentas> muda
    corte = "<ferramentas>"
    assert padrao.split(corte)[0] == nativo.split(corte)[0]
    assert N.FERRAMENTA_FIM in nativo and "Não responda em texto" in nativo
    assert '"tool":' not in nativo


# ── 2. flag ligada: function calling nativo ─────────────────────────────────


def test_2_flag_ligada_declara_as_funcoes_e_termina_com_a_funcao_de_fim(ligada, monkeypatch):
    leitor = T._leitor(["fl2-s1"])
    prov = _ProvNativo([_ler(), _fc("pedir_pagina", doc_id="carf:recurso.pdf", pagina=2,
                                   slot="bullets[0]"), _FIM], [T._emissao()])
    r = T._rodar(prov, monkeypatch, leitor=leitor)
    assert r.success, r.erros
    a = _fase_a(prov)
    assert len(a) == 3
    for c in a:
        assert {d["name"] for d in c["tools"]} == _NOMES
        assert c["tool_config"]["mode"] == "ANY"
        assert set(c["tool_config"]["allowed_function_names"]) == _NOMES
        assert "response_mime_type" not in c
        assert c["temperature"] is None and "seed" not in c
        assert N.FERRAMENTA_FIM in c["prompt"] and "Responda SÓ com um JSON" not in c["prompt"]
    # a ferramenta rodou de fato, e a fase B não mudou
    assert len(leitor.chamadas) == 1
    assert r.documentos_lidos == ["carf:recurso.pdf"] and r.chamadas_ferramenta == 2
    b = [c for c in prov.chamadas if c["_fase"] == "B"]
    assert b and all("tools" not in c and c["response_mime_type"] == "application/json"
                     for c in b)
    assert "fl2-s1" in b[0]["prompt"]
    assert r.fase_a_metricas.model_dump() == {
        "modo": "nativo", "chamadas": 3, "invalidas": 0,
        "custo_usd": pytest.approx(0.003 + 0.002, abs=1e-9),
    }


def test_2b_as_declaracoes_cobrem_o_menu_e_pedem_o_doc_id():
    decl = {d["name"]: d for d in N.declaracoes()}
    assert set(decl) == _NOMES
    for nome in FERRAMENTAS:
        assert decl[nome]["parameters"]["required"][0] == "doc_id"
        assert "slot" in decl[nome]["parameters"]["properties"]
    assert decl["pedir_pagina"]["parameters"]["properties"]["pagina"]["type"] == "integer"
    assert "parameters" not in decl[N.FERRAMENTA_FIM]


# ── 3. budget, breaker e validação iguais nos 2 modos ───────────────────────


def test_3_budget_de_25_por_ficha_e_5_por_documento_no_nativo(ligada, monkeypatch):
    leitor = T._leitor(["fl2-s1"])
    prov = _ProvNativo(lambda i: _ler(), [T._emissao()])
    r = T._rodar(prov, monkeypatch, leitor=leitor)
    assert r.budget_esgotado is True and r.chamadas_ferramenta == 25
    assert len(leitor.chamadas) == 5
    assert prov.n["A"] == 25 and r.fase_a_metricas.chamadas == 25
    assert "teto de 5 chamadas no documento carf:recurso.pdf" in prov.prompts("B")[0]
    assert r.success


def test_3b_circuit_breaker_abre_depois_de_3_falhas_no_nativo(ligada, monkeypatch):
    leitor = T._leitor([], falha=True)
    prov = _ProvNativo([_ler()] * 4 + [_FIM], [T._emissao(trilha=[T._trilha_ok()[0], {
        "slot": "bullets[0]", "doc_id": "carf:acordao.pdf", "paginas": [],
        "trecho_apoio": "Sessão de 17/06/2026."}])])
    r = T._rodar(prov, monkeypatch, leitor=leitor)
    assert len(leitor.chamadas) == 3
    assert "fechada: perguntar_ao_documento no documento carf:recurso.pdf" in prov.prompts("A")[3]
    assert "circuito aberto" in prov.prompts("A")[4]
    assert r.documentos_lidos == [] and r.success


@pytest.mark.parametrize("modo", ["texto", "nativo"])
@pytest.mark.parametrize(("chamada", "erro"), [
    ({"tool": "perguntar_ao_documento", "args": {"doc_id": "carf:nao-existe.pdf",
                                                 "pergunta": "?"}}, "doc_id fora do índice"),
    ({"tool": "pedir_pagina", "args": {"doc_id": "carf:recurso.pdf", "pagina": "dois"}},
     "args.pagina tem de ser inteiro"),
    ({"tool": "perguntar_ao_documento", "args": {"doc_id": "carf:recurso.pdf"}},
     "args.pergunta vazio"),
    ({"tool": "resumir_com_missao", "args": {"doc_id": "carf:acordao.pdf", "missao": "x"}},
     "o documento está no núcleo"),
])
def test_3c_os_argumentos_passam_pelos_mesmos_validadores(monkeypatch, modo, chamada, erro):
    if modo == "nativo":
        monkeypatch.setenv(N.FLAG, "true")
        prov = _ProvNativo([_fc(chamada["tool"], **chamada["args"]), _FIM], [T._emissao()])
    else:
        monkeypatch.delenv(N.FLAG, raising=False)
        prov = T._Prov([json.dumps(chamada), T._FIM], [T._emissao()])
    leitor = T._leitor(["fl2-s1"])
    r = T._rodar(prov, monkeypatch, leitor=leitor)
    assert r.fase_a_metricas.modo == modo
    assert erro in prov.prompts("A")[1]            # o erro volta ao modelo no turno seguinte
    assert r.chamadas_ferramenta == 1 and r.documentos_lidos == []
    assert leitor.chamadas == []


# ── 4. turnos inválidos ─────────────────────────────────────────────────────


def test_4_tres_turnos_sem_funcao_valida_encerram_a_fase_a(ligada, monkeypatch):
    prov = _ProvNativo(["não sei", _fc("funcao_que_nao_existe", x=1), "hmm"],
                       [T._emissao(trilha=[T._trilha_ok()[0], {
                           "slot": "bullets[0]", "doc_id": "carf:acordao.pdf", "paginas": [],
                           "trecho_apoio": "Sessão de 17/06/2026."}])])
    r = T._rodar(prov, monkeypatch)
    assert prov.n["A"] == 3 and r.chamadas_ferramenta == 0 and r.success
    assert r.fase_a_metricas.model_dump(exclude={"custo_usd"}) == {
        "modo": "nativo", "chamadas": 3, "invalidas": 3}
    assert N.ERRO_PROTOCOLO_NATIVO in prov.prompts("A")[1]


def test_4b_um_turno_invalido_conta_e_a_leitura_segue(ligada, monkeypatch):
    prov = _ProvNativo(["texto solto", _ler(), _FIM], [T._emissao()])
    r = T._rodar(prov, monkeypatch)
    assert r.success and r.chamadas_ferramenta == 1
    assert r.fase_a_metricas.model_dump(exclude={"custo_usd"}) == {
        "modo": "nativo", "chamadas": 3, "invalidas": 1}


def test_4c_o_modo_texto_tambem_conta_as_invalidas(desligada, monkeypatch):
    prov = T._Prov(["não sei", T._leituras()[0], T._FIM], [T._emissao()])
    r = T._rodar(prov, monkeypatch)
    assert r.success
    assert r.fase_a_metricas.model_dump(exclude={"custo_usd"}) == {
        "modo": "texto", "chamadas": 3, "invalidas": 1}


@pytest.mark.parametrize(("calls", "esperado"), [
    ([_fc(N.FERRAMENTA_FIM)], {"fim": True}),
    ([_fc("pedir_pagina", doc_id="d", pagina=2)],
     {"tool": "pedir_pagina", "args": {"doc_id": "d", "pagina": 2}}),
    ([{"name": "pedir_pagina", "args": "não é dict"}], {"tool": "pedir_pagina", "args": {}}),
    ([_fc("resumir_com_missao", doc_id="d"), _fc(N.FERRAMENTA_FIM)],
     {"tool": "resumir_com_missao", "args": {"doc_id": "d"}}),   # a PRIMEIRA chamada vale
    ([_fc("outra_funcao")], None),
    ([], None),
    (None, None),
    (["lixo"], None),
])
def test_4d_chamada_nativa_segue_as_regras_de_parse_chamada(calls, esperado):
    assert N.chamada_nativa(calls) == esperado


# ── 5. o provider ───────────────────────────────────────────────────────────


@pytest.fixture
def provider():
    from src.providers.gemini import GeminiProvider

    p = GeminiProvider.__new__(GeminiProvider)
    p._types = gtypes
    p._default_model = "gemini-3.5-flash"
    return p


def test_5_provider_monta_tools_e_tool_config_do_sdk(provider):
    cp = provider._build_config_params(
        temperature=None, max_tokens=100, response_schema=None, model="gemini-3.5-flash",
        tools=N.declaracoes(), tool_config=dict(N.TOOL_CONFIG),
    )
    [tool] = cp["tools"]
    assert isinstance(tool, gtypes.Tool)
    assert [d.name for d in tool.function_declarations] == [d["name"] for d in N.DECLARACOES]
    assert all(isinstance(d, gtypes.FunctionDeclaration) for d in tool.function_declarations)
    fcc = cp["tool_config"].function_calling_config
    assert fcc.mode == gtypes.FunctionCallingConfigMode.ANY
    assert set(fcc.allowed_function_names) == _NOMES
    # R13 continua: sem amostragem
    for campo in ("temperature", "top_p", "top_k", "seed"):
        assert campo not in cp


def test_5b_controle_sem_os_kwargs_o_config_nao_leva_tools(provider):
    cp = provider._build_config_params(
        temperature=None, max_tokens=100, response_schema=None, model="gemini-3.5-flash",
    )
    assert "tools" not in cp and "tool_config" not in cp


def test_5c_function_calls_do_sdk_viram_dicts():
    from src.providers.gemini import _gemini_function_calls

    resp = gtypes.GenerateContentResponse(candidates=[gtypes.Candidate(
        content=gtypes.Content(parts=[
            gtypes.Part(function_call=gtypes.FunctionCall(
                name="pedir_pagina", args={"doc_id": "d", "pagina": 2})),
        ]),
    )])
    assert _gemini_function_calls(resp) == [
        {"name": "pedir_pagina", "args": {"doc_id": "d", "pagina": 2}}]
    assert _gemini_function_calls(gtypes.GenerateContentResponse()) == []
    assert _gemini_function_calls(object()) == []


def test_5d_os_2_call_sites_do_provider_devolvem_function_calls():
    import src.providers.gemini as G

    src = inspect.getsource(G)
    assert src.count('"function_calls": _gemini_function_calls(response)') == 2


# ── 6. gate de fonte: o texto não leva tools ────────────────────────────────


def _agenerate_sem_tools_e_com_parse(fonte: str) -> tuple[bool, bool]:
    """(toda chamada `agenerate` sem `tools`, há chamada a `parse_chamada`)."""
    arvore = ast.parse(fonte)
    sem_tools, com_parse = True, False
    for no in ast.walk(arvore):
        if not isinstance(no, ast.Call):
            continue
        nome = (no.func.attr if isinstance(no.func, ast.Attribute)
                else getattr(no.func, "id", None))
        if nome == "agenerate" and any(k.arg in ("tools", "tool_config") for k in no.keywords):
            sem_tools = False
        if nome == "parse_chamada":
            com_parse = True
    return sem_tools, com_parse


def test_6_o_decisor_do_texto_chama_parse_chamada_e_nao_leva_tools():
    fonte = inspect.getsource(ferr_mod.DecisorTexto)
    assert _agenerate_sem_tools_e_com_parse(fonte) == (True, True)
    # e o default de `navegar` é o texto
    assert inspect.signature(ferr_mod.navegar).parameters["decisor"].default is None
    assert "DecisorTexto(llm, model)" in inspect.getsource(ferr_mod.navegar)


def test_6b_controle_positivo_o_gate_pega_tools_plantado():
    plantado = inspect.getsource(ferr_mod.DecisorTexto).replace(
        "max_tokens=2048,", "max_tokens=2048, tools=[],")
    assert _agenerate_sem_tools_e_com_parse(plantado) == (False, True)
    sem_parse = inspect.getsource(ferr_mod.DecisorTexto).replace("parse_chamada(", "json.loads(")
    assert _agenerate_sem_tools_e_com_parse(sem_parse) == (True, False)


def test_6c_a_flag_so_e_lida_no_redator_v5():
    import src.agents.ficha_writer.agent_v5 as v5
    import src.agents.auditor_ficha.agent_v3 as aud

    assert "fase_a_nativa_ligada()" in inspect.getsource(v5)
    assert "fase_a_nativa" not in inspect.getsource(aud)
    assert "fase_a_nativa" not in inspect.getsource(ferr_mod)


# ── 7. o auditor v3 fica no texto ───────────────────────────────────────────


def test_7_auditor_v3_continua_no_texto_com_a_flag_ligada(ligada, monkeypatch):
    from tests import test_auditor_ficha_v3 as A

    prov = A._Prov(A._ler_recurso(), [A._saida()])
    r = A._rodar(prov, monkeypatch)
    assert r.success
    a = [c for c in prov.chamadas if c["_fase"] == "A"]
    assert a and all("tools" not in c and "tool_config" not in c for c in a)
    assert all('{"fim": true}' in c["prompt"] for c in a)

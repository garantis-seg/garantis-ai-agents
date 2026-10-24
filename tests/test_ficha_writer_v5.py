"""Redator v5 (S4): o agente que lê os autos antes de escrever. Sem rede e sem LLM.

Decisão do Alfredo de 23/10/2026: "núcleo obrigatório + índice navegável". O
provider é um dublê que separa as fases pelo `response_mime_type` (a fase A nunca
leva mime). O Leitor é um dublê injetado. Os documentos são `DocumentoIndexado`
montados à mão, como no teste do qualificador do conexo.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from garantis_shared.llm_models import model_for
from pydantic import ValidationError

import src.agents.ficha_writer.agent as agent_mod
import src.agents.ficha_writer.agent_v5 as v5_mod
import src.agents.ficha_writer.ferramentas as ferr_mod
from src.agents.ficha_writer import write_ficha_fields
from src.agents.ficha_writer.agent_v5 import BUDGET_POR_DOC, BUDGET_POR_FICHA, write_v5
from src.agents.ficha_writer.prompts import PROMPT_VERSION, PROMPT_VERSION_V3
from src.agents.ficha_writer.schemas import (
    FichaWriteFieldsRequest,
    ItemIndice,
    Nucleo,
    TrilhaItem,
)
from src.api.routes.ficha_writer import router
from tests.test_ficha_writer import _esqueleto
from tests.test_qualificador_conexo import _doc

# ── Os autos ────────────────────────────────────────────────────────────────

_ACORDAO = (
    "Acórdão 3102-004.203. Sessão de 17/06/2026. A turma negou provimento ao recurso "
    "voluntário, por maioria. A exigência de PIS e COFINS sobre receitas financeiras "
    "foi mantida."
)
_TRECHO_NUCLEO = "A exigência de PIS e COFINS sobre receitas financeiras foi mantida."
_TRECHO_RECURSO = "O recurso especial não foi admitido em 01/09/2026."


def _doc_recurso():
    return _doc("carf:recurso.pdf", [
        ["Recurso voluntário da IRB.", "A recorrente contesta a tributação de receitas financeiras."],
        [_TRECHO_RECURSO, "Publique-se."],
    ])


def _doc_impugnacao():
    return _doc("carf:impugnacao.pdf", [["Impugnação ao auto de infração de PIS."]])


def _nucleo() -> dict:
    return {
        "acordaos": [{"processo": "16327.721182/2019-21", "doc_id": "carf:acordao.pdf",
                      "texto": _ACORDAO}],
        "peticao_inicial": None,
        "ultima_decisao": {"doc_id": "carf:acordao.pdf", "texto": _ACORDAO},
        "cdas": [],
        "premissas_v3": {"valor": "calculado"},
        "qualificacao_s2c": {"processos": []},
    }


def _indice() -> list[dict]:
    rec, imp = _doc_recurso(), _doc_impugnacao()
    return [
        {"doc_id": rec.doc_id, "nome": "recurso.pdf", "tipo": "recurso", "data": "01/09/2026",
         "processo": "16327.721182/2019-21", "paginas": 2, "n_chars": 180,
         "documento_indexado": rec.to_dict()},
        {"doc_id": imp.doc_id, "nome": "impugnacao.pdf", "tipo": "impugnacao",
         "documento_indexado": imp.to_dict()},
        {"doc_id": "carf:anexo.pdf", "nome": "anexo.pdf", "tipo": "anexo"},
    ]


def _body(**over: Any) -> dict:
    body = {
        "dossie": "Acórdão 3102-004.203, sessão de 17/06/2026.",
        "tipo_ficha": "nova_apolice",
        "trilho": "carf",
        "esqueleto": _esqueleto(),
        "campos": [
            {"nome": "merito.p1", "path": "merito.p1", "max": 600},
            {"nome": "bullets[0]", "path": "bullets[0]", "max": 150},
        ],
        "alertas": [{"codigo": "valor_estimado", "texto": "O valor é estimado."}],
        "nucleo": _nucleo(),
        "indice_navegavel": _indice(),
    }
    body.update(over)
    return body


# ── Emissões ────────────────────────────────────────────────────────────────

_CAMPOS = {
    "merito.p1": "A discussão é a incidência de PIS e COFINS sobre receitas financeiras. "
                 "O CARF manteve a exigência por maioria.",
    "bullets[0]": "O recurso especial não foi admitido em 01/09/2026.",
}
_ALERTAS = [{"codigo": "valor_estimado", "resposta": "acatado", "motivo": "nenhum slot de valor"}]


def _trilha_ok() -> list[dict]:
    return [
        {"slot": "merito.p1", "doc_id": "carf:acordao.pdf", "paginas": [],
         "trecho_apoio": _TRECHO_NUCLEO},
        {"slot": "bullets[0]", "doc_id": "carf:recurso.pdf", "paginas": [2],
         "trecho_apoio": _TRECHO_RECURSO},
    ]


def _emissao(campos: dict | None = None, trilha: list | None = None,
             alertas: list | None = None) -> dict:
    return {"campos": campos if campos is not None else dict(_CAMPOS),
            "alertas_respondidos": alertas if alertas is not None else list(_ALERTAS),
            "trilha_leitura": trilha if trilha is not None else _trilha_ok()}


# ── Dublês ──────────────────────────────────────────────────────────────────


class _Prov:
    """Fase A = sem mime. Fase B = com mime JSON. Guarda toda chamada."""

    def __init__(self, decisoes: list[str] | Callable[[int], str], emissoes: list[dict | str]):
        self.decisoes = decisoes
        self.emissoes = list(emissoes)
        self.chamadas: list[dict] = []
        self.n = {"A": 0, "B": 0}

    async def agenerate(self, **kw):
        fase = "B" if kw.get("response_mime_type") == "application/json" else "A"
        kw["_fase"] = fase
        self.chamadas.append(kw)
        i = self.n[fase]
        self.n[fase] += 1
        if fase == "A":
            texto = (self.decisoes(i) if callable(self.decisoes)
                     else self.decisoes[min(i, len(self.decisoes) - 1)])
        else:
            item = self.emissoes[min(i, len(self.emissoes) - 1)]
            texto = item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
        return SimpleNamespace(text=texto, model=kw["model"], metadata={"cost_usd": 0.001})

    def prompts(self, fase: str) -> list[str]:
        return [c["prompt"] for c in self.chamadas if c["_fase"] == fase]


def _leitor(citacoes: list[str], falha: bool = False):
    chamadas: list[dict] = []

    async def leitor(doc_id, documento, texto):
        chamadas.append({"doc_id": doc_id, "texto": texto})
        if falha:
            raise RuntimeError("leitor caiu")
        return {"success": True, "resposta": "ver [" + "] [".join(citacoes) + "]",
                "citacoes": citacoes, "confianca": 0.9,
                "objeto_da_confianca": "de que o trecho responde a pergunta",
                "encontrou": True, "cost_usd": 0.002}

    leitor.chamadas = chamadas
    return leitor


def _tool(tool: str, doc_id: str, **args) -> str:
    base = {"doc_id": doc_id, "slot": "bullets[0]"}
    if tool == "perguntar_ao_documento":
        base["pergunta"] = "o REsp foi admitido?"
    base.update(args)
    return json.dumps({"tool": tool, "args": base})


_FIM = '{"fim": true}'


def _leituras() -> list[str]:
    return [_tool("perguntar_ao_documento", "carf:recurso.pdf"),
            _tool("pedir_pagina", "carf:recurso.pdf", pagina=2), _FIM]


def _rodar(prov: _Prov, monkeypatch, body: dict | None = None, leitor=None):
    monkeypatch.setattr(v5_mod, "create_provider", lambda *_a, **_k: prov)
    leitor = leitor or _leitor(["fl2-s1"])
    req = FichaWriteFieldsRequest(**(body or _body()))
    return asyncio.run(write_v5(req, "gemini", None, leitor_perguntar=leitor,
                                leitor_resumir=leitor))


# ── (1) o v5 escolhe ferramentas e escreve ──────────────────────────────────


def test_1_v5_le_com_ferramentas_e_escreve_com_trilha(monkeypatch):
    leitor = _leitor(["fl2-s1"])
    prov = _Prov(_leituras(), [_emissao()])
    r = _rodar(prov, monkeypatch, leitor=leitor)

    assert r.success, r.erros
    assert r.campos == _CAMPOS
    assert r.prompt_version.startswith("ficha_writer_v5+")
    assert r.documentos_lidos == ["carf:recurso.pdf"]
    assert r.chamadas_ferramenta == 2 and not r.budget_esgotado
    assert [t.slot for t in r.trilha_leitura] == ["merito.p1", "bullets[0]"]
    assert r.rodadas == 1
    assert [a.codigo for a in r.alertas_respondidos] == ["valor_estimado"]
    assert leitor.chamadas == [{"doc_id": "carf:recurso.pdf", "texto": "o REsp foi admitido?"}]
    # 3 turnos de decisão + 1 escrita. A fase A nunca leva mime.
    assert prov.n == {"A": 3, "B": 1}
    assert all("response_mime_type" not in c for c in prov.chamadas if c["_fase"] == "A")


def test_1b_o_nucleo_entra_inteiro_e_o_indice_sem_conteudo(monkeypatch):
    prov = _Prov(_leituras(), [_emissao()])
    _rodar(prov, monkeypatch)
    decisao, escrita = prov.prompts("A")[0], prov.prompts("B")[0]
    for p in (decisao, escrita):
        assert _ACORDAO in p                        # o núcleo inteiro
        assert "carf:impugnacao.pdf" in p           # o índice
        assert "fl1-s1" not in p                    # sem o conteúdo indexado
        assert "NÚCLEO (LEITURA OBRIGATÓRIA" in p
        assert "MISSÃO DE LEITURA" in p
    assert escrita.rstrip().endswith("</regras_de_redacao>")
    assert "<regras_da_trilha>" in escrita
    # A leitura da fase A chega à escrita com o trecho literal e a página.
    assert _TRECHO_RECURSO in escrita


def test_1c_o_codigo_resolve_o_sid_em_trecho_literal(monkeypatch):
    prov = _Prov(_leituras(), [_emissao()])
    _rodar(prov, monkeypatch)
    segunda = prov.prompts("A")[1]
    assert '"pagina": 2' in segunda and _TRECHO_RECURSO in segunda


def test_1d_rota_responde_v5(monkeypatch):
    prov = _Prov(_leituras(), [_emissao()])
    monkeypatch.setattr(v5_mod, "create_provider", lambda *_a, **_k: prov)
    leitor = _leitor(["fl2-s1"])
    monkeypatch.setattr(ferr_mod, "perguntar_via_doc_reader", leitor)
    monkeypatch.setattr(ferr_mod, "resumir_via_doc_reader", leitor)
    app = FastAPI()
    app.include_router(router)
    resp = TestClient(app).post("/ficha/write-fields", json=_body())
    assert resp.status_code == 200
    j = resp.json()
    assert j["success"] is True
    assert j["trilha_leitura"][1] == {"slot": "bullets[0]", "doc_id": "carf:recurso.pdf",
                                      "paginas": [2], "trecho_apoio": _TRECHO_RECURSO}
    assert j["documentos_lidos"] == ["carf:recurso.pdf"]


def test_1e_sem_documento_legivel_nao_ha_fase_a(monkeypatch):
    prov = _Prov([_FIM], [_emissao(trilha=[_trilha_ok()[0], {
        "slot": "bullets[0]", "doc_id": "carf:acordao.pdf", "paginas": [],
        "trecho_apoio": "Sessão de 17/06/2026."}])])
    r = _rodar(prov, monkeypatch, body=_body(indice_navegavel=[
        {"doc_id": "carf:anexo.pdf", "nome": "anexo.pdf"}]))
    assert r.success, r.erros
    assert prov.n["A"] == 0 and r.chamadas_ferramenta == 0


def test_1f_ferramenta_em_documento_do_nucleo_e_erro_sem_leitor(monkeypatch):
    leitor = _leitor(["fl1-s1"])
    prov = _Prov([_tool("perguntar_ao_documento", "carf:acordao.pdf"), _FIM], [_emissao(
        trilha=[_trilha_ok()[0], {"slot": "bullets[0]", "doc_id": "carf:acordao.pdf",
                                  "paginas": [], "trecho_apoio": "Sessão de 17/06/2026."}])])
    r = _rodar(prov, monkeypatch, leitor=leitor)
    assert r.success
    assert leitor.chamadas == []
    assert "está no núcleo" in prov.prompts("A")[1]


# ── (2) slot de mérito sem trilha: erro estruturado e retry ─────────────────


def test_2_merito_sem_trilha_volta_ao_llm_e_passa_no_retry(monkeypatch):
    sem = _emissao(trilha=[_trilha_ok()[1]])
    prov = _Prov(_leituras(), [sem, _emissao(campos={"merito.p1": _CAMPOS["merito.p1"]},
                                             trilha=[_trilha_ok()[0]], alertas=[])])
    r = _rodar(prov, monkeypatch)
    assert r.success, r.erros
    assert r.rodadas == 2
    retry = prov.prompts("B")[1]
    assert "CORREÇÃO OBRIGATÓRIA" in retry
    assert "merito.p1: slot sem trilha_leitura" in retry
    # O retry pede só o slot que reprovou: o bullet já passou.
    assert '"bullets[0]": "..."' not in retry
    assert {t.slot for t in r.trilha_leitura} == {"merito.p1", "bullets[0]"}


def test_2b_sem_trilha_nas_3_rodadas_vira_success_false_com_erros(monkeypatch):
    """O "422 estruturado" do write-fields: `success=false` e `erros[]` no formato do
    retry ({campo, erro, valor_anterior}), como no v4. O shared reenvia `erros[]`."""
    sem = _emissao(trilha=[_trilha_ok()[1]])
    prov = _Prov(_leituras(), [sem])
    r = _rodar(prov, monkeypatch)
    assert r.success is False and r.rodadas == 3
    assert [e.campo for e in r.erros] == ["merito.p1"]
    assert "slot sem trilha_leitura" in r.erros[0].erro
    assert r.erros[0].valor_anterior == _CAMPOS["merito.p1"]
    assert "merito.p1" not in r.campos and r.campos["bullets[0]"] == _CAMPOS["bullets[0]"]


def test_2c_bullet_opcional_vazio_nao_exige_trilha(monkeypatch):
    body = _body(campos=[{"nome": "merito.p1", "path": "merito.p1", "max": 600},
                         {"nome": "bullets[0]", "path": "bullets[0]", "max": 150,
                          "obrigatorio": False}])
    prov = _Prov([_FIM], [_emissao(campos={**_CAMPOS, "bullets[0]": ""},
                                   trilha=[_trilha_ok()[0]])])
    r = _rodar(prov, monkeypatch, body=body)
    assert r.success, r.erros


# ── (3) doc_id fora do índice, documento não lido, trecho que não está lá ───


@pytest.mark.parametrize(("item", "trecho_do_erro"), [
    ({"doc_id": "carf:nao-existe.pdf", "paginas": [], "trecho_apoio": "x"},
     "fora do núcleo e do índice"),
    # 23/10/2026: o código abre o documento não lido. Sem conteúdo indexado, reprova.
    ({"doc_id": "carf:anexo.pdf", "paginas": [1], "trecho_apoio": "Anexo."},
     "não foi lido na fase A, e o código não consegue abrir"),
    ({"doc_id": "carf:recurso.pdf", "paginas": [2],
      "trecho_apoio": "O recurso especial foi admitido."}, "não está no documento citado"),
    ({"doc_id": "carf:recurso.pdf", "paginas": [9], "trecho_apoio": "Trecho inventado."},
     "página que não existe"),
    ({"doc_id": "carf:acordao.pdf", "paginas": [],
      "trecho_apoio": "O CARF cancelou a exigência."}, "não está no documento citado"),
], ids=["fora_do_indice", "nao_lido_ilegivel", "trecho_inventado", "pagina_inexistente",
        "trecho_fora_do_nucleo"])
def test_3_trilha_invalida_e_erro_do_slot(monkeypatch, item, trecho_do_erro):
    ruim = _emissao(trilha=[_trilha_ok()[0], {"slot": "bullets[0]", **item}])
    prov = _Prov(_leituras(), [ruim])
    r = _rodar(prov, monkeypatch)
    assert r.success is False
    assert {e.campo for e in r.erros} == {"bullets[0]"}
    assert trecho_do_erro in r.erros[0].erro


def test_3b_trecho_sem_acento_e_sem_caixa_casa(monkeypatch):
    t = [_trilha_ok()[0], {"slot": "bullets[0]", "doc_id": "carf:recurso.pdf", "paginas": [2],
                           "trecho_apoio": "o recurso especial nao foi admitido ... publique-se"}]
    prov = _Prov(_leituras(), [_emissao(trilha=t)])
    r = _rodar(prov, monkeypatch)
    assert r.success, r.erros


def test_3c_trilha_sem_slot_valido_vira_erro_da_saida(monkeypatch):
    t = _trilha_ok() + [{"doc_id": "carf:acordao.pdf", "trecho_apoio": "x"}]
    prov = _Prov(_leituras(), [_emissao(trilha=t), _emissao()])
    r = _rodar(prov, monkeypatch)
    assert r.success and r.rodadas == 2
    assert "trilha_leitura: entrada 2 da trilha_leitura inválida" in prov.prompts("B")[1]


# ── (4) budget e circuit breaker ───────────────────────────────────────────


def test_4_budget_de_25_por_ficha_e_5_por_documento(monkeypatch):
    leitor = _leitor(["fl2-s1"])
    prov = _Prov(lambda i: _tool("perguntar_ao_documento", "carf:recurso.pdf"), [_emissao()])
    r = _rodar(prov, monkeypatch, leitor=leitor)
    assert BUDGET_POR_FICHA == 25 and BUDGET_POR_DOC == 5
    assert r.budget_esgotado is True and r.chamadas_ferramenta == 25
    assert len(leitor.chamadas) == 5                       # o teto do documento
    assert prov.n["A"] == 25
    assert "teto de 5 chamadas no documento carf:recurso.pdf" in prov.prompts("B")[0]
    assert r.success                                        # escreve com o que leu


def test_4b_circuit_breaker_abre_depois_de_3_falhas(monkeypatch):
    leitor = _leitor([], falha=True)
    prov = _Prov([_tool("perguntar_ao_documento", "carf:recurso.pdf")] * 4 + [_FIM],
                 [_emissao(trilha=[_trilha_ok()[0], {
                     "slot": "bullets[0]", "doc_id": "carf:acordao.pdf", "paginas": [],
                     "trecho_apoio": "Sessão de 17/06/2026."}])])
    r = _rodar(prov, monkeypatch, leitor=leitor)
    assert len(leitor.chamadas) == 3
    assert "fechada: perguntar_ao_documento no documento carf:recurso.pdf" in prov.prompts("A")[3]
    assert "circuito aberto" in prov.prompts("A")[4]
    assert r.documentos_lidos == []
    assert r.success


def test_4c_tres_turnos_sem_json_encerram_a_fase_a(monkeypatch):
    prov = _Prov(["não sei", "talvez", "hmm"], [_emissao(trilha=[_trilha_ok()[0], {
        "slot": "bullets[0]", "doc_id": "carf:acordao.pdf", "paginas": [],
        "trecho_apoio": "Sessão de 17/06/2026."}])])
    r = _rodar(prov, monkeypatch)
    assert prov.n["A"] == 3 and r.chamadas_ferramenta == 0 and r.success


# ── (5) as validações do v4 continuam no v5 ────────────────────────────────


def test_5_status_do_serpro_e_cifra_reprovam_no_v5(monkeypatch):
    body = _body(campos=[{"nome": "merito.p1", "path": "merito.p1", "max": 600},
                         {"nome": "valor.descricao", "path": "valor.descricao", "max": 250}])
    ruim = _emissao(campos={"merito.p1": _CAMPOS["merito.p1"] + " Dívida ativa ajuizada.",
                            "valor.descricao": "Valor de R$ 10.000,00."},
                    trilha=[_trilha_ok()[0]])
    prov = _Prov([_FIM], [ruim])
    r = _rodar(prov, monkeypatch, body=body)
    assert r.success is False
    erros = {e.campo: e.erro for e in r.erros}
    assert "regra 26" in erros["merito.p1"]
    assert "cifra" in erros["valor.descricao"]


def test_5b_max_e_alerta_sem_resposta_reprovam_no_v5(monkeypatch):
    longo = _emissao(campos={**_CAMPOS, "bullets[0]": "x" * 151}, alertas=[])
    prov = _Prov(_leituras(), [longo])
    r = _rodar(prov, monkeypatch)
    assert r.success is False
    campos = {e.campo for e in r.erros}
    assert campos == {"bullets[0]", "alertas_respondidos"}


def test_5c_processo_fora_dos_citaveis_reprova_no_v5(monkeypatch):
    ruim = _emissao(campos={**_CAMPOS, "merito.p1": "Ver o processo 16327.720083/2022-28."})
    prov = _Prov(_leituras(), [ruim])
    r = _rodar(prov, monkeypatch)
    assert r.success is False
    assert "fora dos permitidos" in r.erros[0].erro


# ── (6) compatibilidade: v4 e v3 seguem iguais com o request antigo ─────────


class _Simples:
    def __init__(self, texto: str):
        self.texto = texto
        self.chamadas: list[dict] = []

    async def agenerate(self, **kw):
        self.chamadas.append(kw)
        return SimpleNamespace(text=self.texto, model="gemini-fake", metadata={"cost_usd": 0.01})


def test_6_request_v4_segue_v4(monkeypatch):
    prov = _Simples(json.dumps({"campos": _CAMPOS, "alertas_respondidos": _ALERTAS},
                               ensure_ascii=False))
    monkeypatch.setattr(agent_mod, "create_provider", lambda *_a, **_k: prov)
    body = _body()
    del body["nucleo"], body["indice_navegavel"]
    r = asyncio.run(write_ficha_fields(body))
    assert r.success and r.prompt_version == PROMPT_VERSION == "ficha_writer_v4"
    assert len(prov.chamadas) == 1
    assert "NÚCLEO" not in prov.chamadas[0]["prompt"]
    assert "trilha_leitura" not in prov.chamadas[0]["prompt"]
    assert r.trilha_leitura == [] and r.documentos_lidos == [] and r.chamadas_ferramenta == 0


def test_6b_request_v3_segue_v3(monkeypatch):
    prov = _Simples(json.dumps({"merito.p1": "a", "bullets[0]": "b"}))
    monkeypatch.setattr(agent_mod, "create_provider", lambda *_a, **_k: prov)
    r = asyncio.run(write_ficha_fields({
        "dossie": {"razao_social": "ACME"}, "tipo_ficha": "nova_apolice",
        "campos": [{"nome": "merito.p1", "max": 600}, {"nome": "bullets[0]", "max": 150}]}))
    assert r.success and r.prompt_version == PROMPT_VERSION_V3
    assert r.campos == {"merito.p1": "a", "bullets[0]": "b"}
    assert len(prov.chamadas) == 1


def test_6c_o_prompt_v4_nao_mudou_com_o_v5():
    """O v5 importa os blocos do v4. O prompt v4 de um request v4 fica byte a byte
    igual ao de um request v4 sem os campos novos no schema."""
    from src.agents.ficha_writer.livro import chave_livro, resolver_slots
    from src.agents.ficha_writer.prompts_v4 import build_prompt_v4

    body = _body()
    del body["nucleo"], body["indice_navegavel"]
    req = FichaWriteFieldsRequest(**body)
    slots, _ = resolver_slots(req, req.campos)
    p = build_prompt_v4(req, chave=chave_livro(req), slots=slots, alertas=req.alertas,
                        citaveis=[], fence_token="t0")
    assert "NÚCLEO" not in p and "ÍNDICE" not in p and "trilha" not in p


def test_6d_meio_v5_e_rejeitado():
    body = _body()
    del body["indice_navegavel"]
    with pytest.raises(ValidationError, match="juntos"):
        FichaWriteFieldsRequest(**body)
    body = _body()
    del body["esqueleto"]
    with pytest.raises(ValidationError, match="exige esqueleto"):
        FichaWriteFieldsRequest(**body)


# ── (7) schemas fechados ───────────────────────────────────────────────────


def test_7_trilha_rejeita_chave_extra():
    with pytest.raises(ValidationError):
        TrilhaItem.model_validate(
            {"slot": "merito.p1", "doc_id": "a", "trecho_apoio": "t", "nota": "x"})


# 23/10/2026: o núcleo e o item do índice são dado do shared. Chave desconhecida
# dentro deles vira log, não 422 (defeito do 422 da rodada IRB 1481420).
@pytest.mark.parametrize(("modelo", "dados"), [
    (Nucleo, {**_nucleo(), "chave_nova": 1}),
    (Nucleo, {"acordaos": [{"doc_id": "a", "texto": "t", "relator": "x"}]}),
    (ItemIndice, {"doc_id": "a", "chave_nova": "x"}),
], ids=["nucleo", "acordao", "indice"])
def test_7_nucleo_e_indice_ignoram_chave_desconhecida_com_log(modelo, dados, caplog):
    with caplog.at_level("WARNING"):
        m = modelo.model_validate(dados)
    assert "FICHA_NUCLEO_CHAVE_IGNORADA" in caplog.text
    assert "chave_nova" not in m.model_dump() and "relator" not in json.dumps(
        m.model_dump(mode="json"))


def test_7b_trecho_apoio_acima_de_200_e_rejeitado():
    with pytest.raises(ValidationError):
        TrilhaItem(slot="merito.p1", doc_id="a", trecho_apoio="x" * 201)


def test_7c_request_v5_com_chave_extra_e_422_na_rota():
    app = FastAPI()
    app.include_router(router)
    resp = TestClient(app).post("/ficha/write-fields", json=_body(indice_extra=[]))
    assert resp.status_code == 422


# ── (8) modelo do papel ────────────────────────────────────────────────────


def test_8_o_v5_usa_o_papel_ficha_redacao(monkeypatch):
    prov = _Prov(_leituras(), [_emissao()])
    r = _rodar(prov, monkeypatch)
    assert v5_mod.DEFAULT_MODEL == model_for("ficha_redacao")
    assert {c["model"] for c in prov.chamadas} == {model_for("ficha_redacao")}
    assert r.model == model_for("ficha_redacao")


# ── (8) contrato com o shared 1.826 (23/10/2026) ────────────────────────────
#
# A forma real que o shared manda (`v2.montar_nucleo` + `v2.indice_navegavel`),
# gravada na rodada IRB 1481420. O redator v5 respondeu 422 a ela.

_FIXTURE = Path(__file__).parent / "fixtures" / "nucleo_shared_1826.json"


def _shared_1826() -> dict:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def test_8_contrato_nucleo_do_shared_1826_valida_sem_erro(caplog):
    real = _shared_1826()
    with caplog.at_level("WARNING"):
        req = FichaWriteFieldsRequest(**_body(nucleo=real["nucleo"],
                                              indice_navegavel=real["indice_navegavel"]))
    assert "FICHA_NUCLEO_CHAVE_IGNORADA" not in caplog.text  # nenhuma chave perdida
    n = req.nucleo
    assert req.modo_v5
    assert n.cdas.divida_ativa["data"] == "22/10/2026"
    assert n.cdas.valor_cdas == 0.0 and n.cdas.inscricoes_membros == []
    assert n.metadados["conexo_id"] == 1481420
    assert n.qualificacao["modo"] == "capa" and n.premissas_v3
    [doc] = n.documentos()
    assert doc.papel == "decisao_pa" and doc.n_chars == len(doc.texto) == 95225
    [it] = req.indice_navegavel
    assert it.processo == "16327721182201921" and it.grau == "sem_ancora"


def test_8b_rota_aceita_a_forma_do_shared(monkeypatch):
    """A rota não dá 422. O LLM é dublê: o teste é só do contrato."""
    real = _shared_1826()
    prov = _Prov([_FIM], [_emissao(trilha=[])])
    monkeypatch.setattr(v5_mod, "create_provider", lambda *_a, **_k: prov)
    app = FastAPI()
    app.include_router(router)
    resp = TestClient(app).post("/ficha/write-fields", json=_body(
        nucleo=real["nucleo"], indice_navegavel=real["indice_navegavel"]))
    assert resp.status_code == 200, resp.text[:500]


def test_8c_qualificacao_aceita_os_2_nomes():
    a = Nucleo.model_validate({"qualificacao": {"modo": "capa"}})
    b = Nucleo.model_validate({"qualificacao_s2c": {"modo": "capa"}})
    assert a.qualificacao == b.qualificacao == {"modo": "capa"}


def test_8d_o_prompt_leva_cdas_e_metadados_legiveis():
    real = _shared_1826()
    nucleo = Nucleo.model_validate(real["nucleo"])
    out = ferr_mod.nucleo_legivel(nucleo)
    assert out["cdas"][0].startswith("Dívida ativa (esqueleto): tem: False")
    assert "data: 22/10/2026" in out["cdas"][0]
    assert "Valor das CDAs (R$): 0.0" in out["cdas"]
    assert "Dívida ativa verificada em: sem data" in out["cdas"]
    assert "conexo.razao_social: IRB-BRASIL RESSEGUROS S.A." in out["metadados"]
    assert "membros[0].item_type: processo_carf" in out["metadados"]
    assert not any(linha.startswith("premissas_v3") for linha in out["metadados"])
    assert out["documentos"][0]["texto"] == nucleo.documentos()[0].texto
    assert out["qualificacao"]["modo"] == "capa"


def test_8e_cdas_em_lista_continua_valendo():
    n = Nucleo.model_validate({"cdas": [{"numero": "8061900012345", "valor": 10.0}]})
    assert ferr_mod.cdas_legiveis(n.cdas) == ["CDA 1: numero: 8061900012345; valor: 10.0"]



# ── (9) determinismo máximo: o código conserta antes de reprovar (23/10/2026) ──
#
# Rodada real de 23/10/2026 (executor v2 do shared 1.827, ai-agents rev 00411):
# IRB perdeu 3 rodadas por `trecho_apoio` acima de 200 caracteres; Claro citou 2
# vezes um documento que a fase A não leu e saiu com 4 slots vazios.

_LONGO_NUCLEO = (
    _ACORDAO + " O relator votou pela manutenção integral do lançamento, com base na "
    "jurisprudência da turma sobre a receita financeira das instituições."
)


def _nucleo_longo() -> dict:
    n = _nucleo()
    n["acordaos"] = [{"processo": "16327.721182/2019-21", "doc_id": "carf:acordao.pdf",
                      "texto": _LONGO_NUCLEO}]
    n["ultima_decisao"] = {"doc_id": "carf:acordao.pdf", "texto": _LONGO_NUCLEO}
    return n


def test_9a_cortar_trecho_no_fim_de_palavra():
    from src.agents.ficha_writer.ferramentas import cortar_trecho

    assert cortar_trecho("curto", 200) == "curto"
    t = "palavra " * 40
    c = cortar_trecho(t, 200)
    assert len(c) <= 200 and t.startswith(c) and c.endswith("palavra")
    assert cortar_trecho("a ... b" + "x" * 300, 4) == "a"     # sem "..." solto no fim
    assert cortar_trecho(None, 200) is None                    # o schema dá o erro


def test_9b_trecho_acima_de_200_e_cortado_e_aceito(monkeypatch):
    """IRB: o modelo copiou o acórdão inteiro do núcleo. O código corta e aceita."""
    assert len(_LONGO_NUCLEO) > 200
    t = [{"slot": "merito.p1", "doc_id": "carf:acordao.pdf", "paginas": [],
          "trecho_apoio": _LONGO_NUCLEO}, _trilha_ok()[1]]
    prov = _Prov(_leituras(), [_emissao(trilha=t)])
    r = _rodar(prov, monkeypatch, body=_body(nucleo=_nucleo_longo()))
    assert r.success, r.erros
    assert r.rodadas == 1
    trecho = r.trilha_leitura[0].trecho_apoio
    assert len(trecho) <= 200 and _LONGO_NUCLEO.startswith(trecho)
    assert _LONGO_NUCLEO[len(trecho)] == " "                  # fim de palavra


def test_9c_prefixo_de_80_caracteres_basta(monkeypatch):
    trecho = _ACORDAO[:90] + " e o resto foi parafraseado"
    t = [{"slot": "merito.p1", "doc_id": "carf:acordao.pdf", "paginas": [],
          "trecho_apoio": trecho}, _trilha_ok()[1]]
    prov = _Prov(_leituras(), [_emissao(trilha=t)])
    assert _rodar(prov, monkeypatch).success
    # Abaixo de 80 caracteres certos, o prefixo não casa (23/10/2026).
    ruim = [{**t[0], "trecho_apoio": _ACORDAO[:60] + " e o resto foi parafraseado"}, t[1]]
    prov = _Prov(_leituras(), [_emissao(trilha=ruim)])
    r = _rodar(prov, monkeypatch)
    assert r.success is False and "não está no documento citado" in r.erros[0].erro


@pytest.mark.parametrize(("paginas", "esperado"), [
    (None, [2]), ([], [2]), ([1], [2]), ([9], [2]), (2, [2]),
], ids=["nula", "vazia", "errada", "inexistente", "inteiro"])
def test_9d_o_codigo_acha_a_pagina_do_documento_do_indice(monkeypatch, paginas, esperado):
    t = [_trilha_ok()[0], {"slot": "bullets[0]", "doc_id": "carf:recurso.pdf",
                           "paginas": paginas, "trecho_apoio": _TRECHO_RECURSO}]
    prov = _Prov(_leituras(), [_emissao(trilha=t)])
    r = _rodar(prov, monkeypatch)
    assert r.success, r.erros
    assert r.trilha_leitura[1].paginas == esperado


def test_9e_paginas_opcional_no_documento_do_nucleo(monkeypatch):
    t = [{"slot": "merito.p1", "doc_id": "carf:acordao.pdf", "paginas": None,
          "trecho_apoio": _TRECHO_NUCLEO},
         {"slot": "bullets[0]", "doc_id": "carf:acordao.pdf", "paginas": [7],
          "trecho_apoio": "Sessão de 17/06/2026."}]
    prov = _Prov([_FIM], [_emissao(trilha=t)])
    r = _rodar(prov, monkeypatch)
    assert r.success, r.erros
    assert r.trilha_leitura[0].paginas == []


def test_9f_documento_nao_lido_o_codigo_abre_e_aceita(monkeypatch):
    """Claro: o modelo citou um documento que a fase A não leu. O código abre o
    documento, acha o trecho e aceita. O aviso registra a verificação."""
    t = [_trilha_ok()[0], {"slot": "bullets[0]", "doc_id": "carf:impugnacao.pdf",
                           "paginas": [], "trecho_apoio": "Impugnação ao auto de infração"}]
    prov = _Prov([_FIM], [_emissao(trilha=t)])
    r = _rodar(prov, monkeypatch)
    assert r.success, r.erros
    assert r.documentos_lidos == []                         # a fase A não leu
    assert r.trilha_leitura[1].doc_id == "carf:impugnacao.pdf"
    assert r.trilha_leitura[1].paginas == [1]
    assert any(a.startswith("verificado_pelo_codigo: bullets[0]") and
               "carf:impugnacao.pdf" in a for a in r.avisos)


def test_9g_documento_nao_lido_sem_achar_da_a_lista_de_citaveis(monkeypatch):
    t = [_trilha_ok()[0], {"slot": "bullets[0]", "doc_id": "carf:impugnacao.pdf",
                           "paginas": [], "trecho_apoio": "O REsp foi provido."}]
    prov = _Prov(_leituras(), [_emissao(trilha=t), _emissao()])
    r = _rodar(prov, monkeypatch)
    assert r.success and r.rodadas == 2
    retry = prov.prompts("B")[1]
    assert "o código abriu o documento, e o trecho não está nele" in retry
    assert 'Cite só documentos desta lista: ["carf:acordao.pdf", "carf:recurso.pdf"]' in retry
    # O prompt repete a lista num bloco próprio, na 1ª rodada e no retry.
    for p in prov.prompts("B"):
        assert ('DOCUMENTOS QUE VOCÊ PODE CITAR NA TRILHA ===\nCite só estes doc_id (o '
                'núcleo e o que você leu com as ferramentas):\n'
                '["carf:acordao.pdf", "carf:recurso.pdf"]') in p


def test_9h_budget_de_verificacao_de_5_documentos_por_ficha():
    from src.agents.ficha_writer.ferramentas import MAX_VERIFICACOES, Autos

    assert MAX_VERIFICACOES == 5
    req = FichaWriteFieldsRequest(**_body())
    autos = Autos(req.nucleo, req.indice_navegavel, max_verificacoes=1)
    ok = autos.verificar("carf:impugnacao.pdf", [], "Impugnação ao auto de infração de PIS.")
    assert ok.erro is None and ok.verificado_pelo_codigo
    # O mesmo documento não gasta o budget de novo.
    assert autos.verificar("carf:impugnacao.pdf", [1], "auto de infração").erro is None
    sem = autos.verificar("carf:recurso.pdf", [2], _TRECHO_RECURSO)
    assert "o código já abriu 1 documentos" in sem.erro
    assert "Cite só documentos desta lista" in sem.erro
    assert autos.lidos == set()                             # a fase A não muda


def test_9i_slot_vazio_na_ultima_rodada_diz_o_motivo_anterior(monkeypatch):
    """Claro: os 4 slots vazios saíram com erro genérico. Agora o erro diz o slot e
    o motivo da rodada anterior."""
    r1 = _emissao(trilha=[{"slot": "merito.p1", "doc_id": "carf:anexo.pdf", "paginas": [],
                           "trecho_apoio": "Anexo."}, _trilha_ok()[1]])
    vazio = _emissao(campos={"merito.p1": ""}, trilha=[], alertas=[])
    prov = _Prov(_leituras(), [r1, vazio, vazio])
    r = _rodar(prov, monkeypatch)
    assert r.success is False and r.rodadas == 3
    [e] = r.erros
    assert e.campo == "merito.p1"
    assert e.erro.startswith("merito.p1: slot obrigatório vazio na rodada 3.")
    assert "Motivo da rodada anterior: merito.p1: trilha_leitura:" in e.erro
    assert "carf:anexo.pdf" in e.erro
    assert "Motivo da rodada anterior" in prov.prompts("B")[2]


def test_9j_slot_vazio_usa_o_motivo_que_veio_do_shared(monkeypatch):
    body = _body(campos_com_erro=[{"nome": "merito.p1", "erro": "S5: tese sem documento",
                                   "valor_anterior": "x"}])
    vazio = _emissao(campos={**_CAMPOS, "merito.p1": ""}, trilha=[_trilha_ok()[1]])
    prov = _Prov(_leituras(), [vazio])
    r = _rodar(prov, monkeypatch, body=body)
    erro = {e.campo: e.erro for e in r.erros}["merito.p1"]
    assert "Motivo da rodada anterior: S5: tese sem documento" in erro


# ── (10) a conferência do trecho normaliza o texto de PDF (23/10/2026) ─────────
#
# Rodada real IRB 1481420 (ai-agents rev 00412): o redator reprovou `bullets[2]` 3
# vezes com "o trecho não está, literal, no documento citado". O trecho estava no
# acórdão (`Decisao_16327721182201921_3102-004203.PDF`, núcleo de 95.225
# caracteres). O cabeçalho da página seguinte cortava a frase no meio. O recorte
# abaixo é o texto real do núcleo: a passagem do voto de qualidade e mais 5
# cabeçalhos de página, com o corpo encurtado.

_IRB_NUCLEO = (
    'de votos, em conhecer do recurso voluntário e negar-lhe provimento quanto à exclusão da \n'
    'incidência das contribuições referentes às receitas de variações cambiais decorrentes de prêmios \n'
    'de seguros; ii) por voto de qualidade, para: a) negar-lhe provimento quanto à exclusão da \n'
    'Fl. 1094\n'
    'DF  CARF  MF\n'
    'Original\n'
    '\n'
    'DOCUMENTO VALIDADO \n'
    'ACÓRDÃO  3102-004.203 – 3ª SEÇÃO/1ª CÂMARA/2ª TURMA ORDINÁRIA \n'
    ' PROCESSO  16327.721182/2019-21 \n'
    ' 2 \n'
    'incidência das contribuições referentes às receitas financeiras dos ativos garantidores. Vencidos os \n'
    'conselheiros Jorge Luís Cabral, Wilson Antônio de Souza Corrêa e Joana Maria de Oliveira \n'
    'Guimarães; e b) recusar a proposta de diligência feita pela conselheira Joana Maria de Oliveira \n'
    'Guimarães. Vencidos os conselheiros Joana Maria de Oliveira Guimarães, Sabrina Coutinho \n'
    '(...)\n'
    'segurança, rentabilidade e solvência. E são justamente os rendimentos financeiros \n'
    'Fl. 1095\n'
    'DF  CARF  MF\n'
    'Original\n'
    '\n'
    'DOCUMENTO VALIDADO \n'
    'ACÓRDÃO  3102-004.203 – 3ª SEÇÃO/1ª CÂMARA/2ª TURMA ORDINÁRIA \n'
    ' PROCESSO  16327.721182/2019-21 \n'
    ' 3 \n'
    'das reservas técnicas que dão ensejo às receitas financeiras auferidas pelas \n'
    'entidades seguradoras e de previdência complementar aberta. \n'
    '(...)\n'
    'cálculo. O valor a ser tributado é representado pela receita operacional total, \n'
    'Fl. 1096\n'
    'DF  CARF  MF\n'
    'Original\n'
    '\n'
    'DOCUMENTO VALIDADO \n'
    'ACÓRDÃO  3102-004.203 – 3ª SEÇÃO/1ª CÂMARA/2ª TURMA ORDINÁRIA \n'
    ' PROCESSO  16327.721182/2019-21 \n'
    ' 4 \n'
    'incluindo as receitas financeiras auferidas nos investimentos compulsórios (Anexo \n'
    'I para o ano-calendário de 2015 e Anexo III para o ano-calendário de 2016) e as \n'
    '(...)\n'
    'correspondentes provas documentais, não é hábil a alterar o lançamento nem a \n'
    'justificar pedido de diligência ou perícia. \n'
    'Fl. 1097\n'
    'DF  CARF  MF\n'
    'Original\n'
    '\n'
    'DOCUMENTO VALIDADO \n'
    'ACÓRDÃO  3102-004.203 – 3ª SEÇÃO/1ª CÂMARA/2ª TURMA ORDINÁRIA \n'
    ' PROCESSO  16327.721182/2019-21 \n'
    ' 5 \n'
    'ASSUNTO: CONTRIBUIÇÃO PARA O FINANCIAMENTO DA SEGURIDADE SOCIAL - \n'
    'COFINS  \n'
    'Período de apuração: 01/01/2015 a 31/12/2016  \n'
    '(...)\n'
    'pessoa jurídica, obtidas a partir de investimentos necessários para o exercício da \n'
    'Fl. 1098\n'
    'DF  CARF  MF\n'
    'Original\n'
    '\n'
    'DOCUMENTO VALIDADO \n'
    'ACÓRDÃO  3102-004.203 – 3ª SEÇÃO/1ª CÂMARA/2ª TURMA ORDINÁRIA \n'
    ' PROCESSO  16327.721182/2019-21 \n'
    ' 6 \n'
    'atividade fim, integram o seu faturamento e, portanto, compõem a base de \n'
    'cálculo, não se justificando sua exclusão. \n'
    '(...)\n'
    'O Recurso Voluntário é tempestivo e atende os demais requisitos de \n'
    'admissibilidade, devendo, então, ser conhecido. \n'
    'Fl. 1099\n'
    'DF  CARF  MF\n'
    'Original\n'
    '\n'
    'DOCUMENTO VALIDADO \n'
    'ACÓRDÃO  3102-004.203 – 3ª SEÇÃO/1ª CÂMARA/2ª TURMA ORDINÁRIA \n'
    ' PROCESSO  16327.721182/2019-21 \n'
    ' 7 \n'
    'Conforme relatado, trata-se de autos de infração de PIS e Cofins relativos aos anos \n'
    'de 2015 e 2016 lavrados porque a fiscalização entendeu que a empresa deixou de incluir na base \n'
    '(...)\n'
)

_TRECHO_IRB = (
    "ii) por voto de qualidade, para: a) negar-lhe provimento quanto à exclusão da "
    "incidência das contribuições referentes às receitas financeiras dos ativos "
    "garantidores."
)


def _nucleo_irb() -> dict:
    n = _nucleo()
    n["acordaos"] = [{"processo": "16327.721182/2019-21", "doc_id": "carf:acordao.pdf",
                      "texto": _IRB_NUCLEO}]
    n["ultima_decisao"] = {"doc_id": "carf:acordao.pdf", "texto": _IRB_NUCLEO}
    return n


def test_10a_trecho_real_do_irb_casa_apesar_do_cabecalho_de_pagina():
    from src.agents.ficha_writer.ferramentas import normalizar, trecho_confere

    assert normalizar(_TRECHO_IRB) not in normalizar(_IRB_NUCLEO)   # o defeito de antes
    casou = trecho_confere(_TRECHO_IRB, _IRB_NUCLEO)
    assert casou and casou.metodo == "literal"


@pytest.mark.parametrize("trecho", [
    # Inventado: as palavras são do documento, a frase não é.
    "por voto de qualidade, negar provimento ao recurso de ofício da Fazenda Nacional "
    "quanto à multa isolada aplicada sobre as estimativas mensais.",
    # A decisão invertida: "dar" no lugar de "negar".
    _TRECHO_IRB.replace("negar-lhe", "dar-lhe"),
    # A negação a mais.
    _TRECHO_IRB.replace("a) negar-lhe provimento", "a) não negar-lhe provimento"),
], ids=["inventado", "dar_por_negar", "negacao_a_mais"])
def test_10b_trecho_que_nao_esta_no_documento_reprova(trecho):
    from src.agents.ficha_writer.ferramentas import trecho_confere

    casou = trecho_confere(trecho, _IRB_NUCLEO)
    assert not casou and casou.metodo is None


def test_10c_hifenizacao_quebras_aspas_e_acentos_sinteticos():
    from src.agents.ficha_writer.ferramentas import trecho_confere

    pdf = ("O  colegiado  decidiu  que  as  contribui-\nções  incidem  sobre  o  “resultado\n"
           "econômico-\nfinanceiro”  da  segura-\n  dora — conforme  o  Acórdão  3401-\n004.511..")
    trecho = ('O colegiado decidiu que as contribuicoes incidem sobre o "resultado '
              'economico-financeiro" da seguradora - conforme o acordao 3401-004.511.')
    casou = trecho_confere(trecho, pdf)
    assert casou and casou.metodo == "literal"
    # Um número diferente nunca casa (o trecho tem menos de 80 caracteres).
    curto = "da seguradora - conforme o acordao 3401-004.511"
    assert trecho_confere(curto, pdf).metodo == "literal"
    assert not trecho_confere(curto.replace("004.511", "004.512"), pdf)


def test_10d_prefixo_e_similar_dao_o_metodo():
    from src.agents.ficha_writer.ferramentas import trecho_confere

    texto = ("A turma manteve a exigência de PIS e COFINS sobre as receitas financeiras das "
             "reservas técnicas da seguradora, por voto de qualidade, na sessão de junho.")
    prefixo = trecho_confere(texto[:85] + " e o resto o modelo escreveu de cabeça.", texto)
    assert prefixo and prefixo.metodo == "prefixo"
    typo = trecho_confere("A turma mantteve a exigencia de PIS e COFINS sobre as receitas "
                          "financeiras", texto)
    assert typo and typo.metodo == "similar" and typo.similaridade >= 0.90
    # Um número diferente nunca casa, nem com a grafia quase igual.
    processo = ("O processo 16327.721182/2019-21 trata da exigência de PIS e COFINS sobre "
                "as receitas financeiras.")
    assert trecho_confere(processo.replace("financeiras", "financeiraz"), processo)
    assert not trecho_confere(processo.replace("721182", "721183"), processo)
    # Curto demais para a similaridade: só o literal vale.
    assert not trecho_confere("A turma mantteve", texto)


def test_10e_v5_aceita_o_trecho_real_na_primeira_rodada(monkeypatch):
    t = [{"slot": "merito.p1", "doc_id": "carf:acordao.pdf", "paginas": [],
          "trecho_apoio": _TRECHO_IRB}, _trilha_ok()[1]]
    prov = _Prov(_leituras(), [_emissao(trilha=t)])
    r = _rodar(prov, monkeypatch, body=_body(nucleo=_nucleo_irb()))
    assert r.success, r.erros
    assert r.rodadas == 1
    assert not any(a.startswith("trecho_aproximado") for a in r.avisos)


def test_10f_v5_avisa_quando_o_trecho_casa_por_similaridade(monkeypatch):
    trecho = _TRECHO_IRB.replace("provimento", "provimentto")
    t = [{"slot": "merito.p1", "doc_id": "carf:acordao.pdf", "paginas": [],
          "trecho_apoio": trecho}, _trilha_ok()[1]]
    prov = _Prov(_leituras(), [_emissao(trilha=t)])
    r = _rodar(prov, monkeypatch, body=_body(nucleo=_nucleo_irb()))
    assert r.success and r.rodadas == 1, r.erros
    assert ("trecho_aproximado: merito.p1: o trecho casou por similar no documento "
            "carf:acordao.pdf") in r.avisos


def test_10g_v5_reprova_o_trecho_inventado_no_nucleo_real(monkeypatch):
    t = [{"slot": "merito.p1", "doc_id": "carf:acordao.pdf", "paginas": [],
          "trecho_apoio": _TRECHO_IRB.replace("negar-lhe", "dar-lhe")}, _trilha_ok()[1]]
    prov = _Prov(_leituras(), [_emissao(trilha=t)] * 3)
    r = _rodar(prov, monkeypatch, body=_body(nucleo=_nucleo_irb()))
    assert r.success is False
    assert "o trecho não está no documento citado" in r.erros[0].erro


# ── (11) fato sem fonte: data, número e esgotamento (23/10/2026) ──────────────
#
# Rodada real do IRB 1481420 (rev 00413): o redator v5 escreveu "não foi admitido em
# 01/09/2026, encerrando a via administrativa" em 4 slots. A data não existe em fonte
# nenhuma, e o esqueleto marca a CSRF `em_andamento`. A fixture traz o núcleo real e a
# saída real do redator.

_FIXTURE_IRB = Path(__file__).parent / "fixtures" / "irb_1481420_rev00413.json"

#: Os 4 slots com a data inventada ou o esgotamento, reescritos sem o fato sem fonte.
_SLOTS_LIMPOS = {
    "processo_administrativo.resumo": (
        "Autos de infração exigindo PIS e COFINS no regime cumulativo sobre receitas "
        "financeiras dos ativos garantidores das reservas técnicas e sobre variações "
        "cambiais dos anos de 2015 e 2016. A DRJ manteve a exigência e o CARF negou "
        "provimento integral ao recurso voluntário. O recurso especial está em julgamento "
        "na Câmara Superior."),
    "ultima_ocorrencia.texto": "Recurso especial em julgamento na Câmara Superior desde "
                               "11/10/2026.",
    "bullets[0]": "Recurso especial em julgamento na CSRF desde 11/10/2026: a via "
                  "administrativa continua aberta.",
    "merito.p2": (
        "A DRJ julgou a impugnação improcedente. Em 17/06/2026, o CARF negou provimento "
        "integral ao recurso voluntário (acórdão 3102-004.203): unânime quanto às "
        "variações cambiais de prêmios e por voto de qualidade quanto às receitas "
        "financeiras dos ativos garantidores."),
}


def _irb() -> dict:
    return json.loads(_FIXTURE_IRB.read_text(encoding="utf-8"))


def _campos_irb(fx: dict) -> dict[str, str]:
    from src.agents.ficha_writer.validacao import slots_de_texto

    nomes = {s["nome"] for s in fx["slots"]}
    return {k: v for k, v in slots_de_texto(fx["ficha"]).items() if k in nomes}


def _body_irb(fx: dict) -> dict:
    campos = _campos_irb(fx)
    return {
        "dossie": "", "tipo_ficha": fx["tipo_ficha"], "trilho": fx["trilho"],
        "esqueleto": fx["ficha"],
        "campos": [{"nome": s["nome"], "path": s["nome"], "max": 2000,
                    "obrigatorio": s["obrigatorio"]}
                   for s in fx["slots"] if s["nome"] in campos],
        "alertas": fx["alertas"], "processos_citaveis": fx["processos_citaveis"],
        "nucleo": fx["nucleo"], "indice_navegavel": fx["indice_navegavel"],
    }


def _emissao_irb(fx: dict, campos: dict[str, str]) -> dict:
    alertas = [{"codigo": a["codigo"], "resposta": "acatado", "motivo": "conferido"}
               for a in fx["alertas"]]
    return {"campos": campos, "alertas_respondidos": alertas,
            "trilha_leitura": fx["trilha_leitura"]}


def test_11a_a_saida_real_do_irb_reprova_a_data_inventada_e_o_esgotamento(monkeypatch):
    fx = _irb()
    real = _emissao_irb(fx, _campos_irb(fx))
    prov = _Prov([_FIM], [real] * 3)
    r = _rodar(prov, monkeypatch, body=_body_irb(fx))

    assert r.success is False and r.rodadas == 3
    sem_data = {e.campo for e in r.erros if e.erro.startswith("fato sem fonte: 01/09/2026")}
    assert sem_data == {"ultima_ocorrencia.texto", "bullets[0]", "merito.p2"}
    esgot = {e.campo for e in r.erros
             if e.erro.startswith("afirmação de esgotamento sem fonte")}
    assert esgot == {"processo_administrativo.resumo", "ultima_ocorrencia.texto",
                     "bullets[0]", "merito.p2"}
    # O erro é estruturado: o texto que reprovou vai em valor_anterior.
    e = next(e for e in r.erros if e.campo == "bullets[0]")
    assert e.valor_anterior == real["campos"]["bullets[0]"]
    # Os slots sem fato sem fonte passam.
    assert r.campos["merito.p1"] == real["campos"]["merito.p1"]
    assert "bullets[0]" not in r.campos
    # O retry diz ao modelo as datas e os números permitidos.
    retry = prov.prompts("B")[1]
    assert "datas permitidas:" in retry and "17/06/2026" in retry and "11/10/2026" in retry
    permitidas = retry.split("datas permitidas:")[1].split(";")[0]
    assert "17/06/2026" in permitidas and "01/09/2026" not in permitidas
    assert "3102-004.203" in retry.split("números permitidos:")[1]


def test_11b_a_saida_limpa_do_irb_passa_na_primeira_rodada(monkeypatch):
    fx = _irb()
    prov = _Prov([_FIM], [_emissao_irb(fx, {**_campos_irb(fx), **_SLOTS_LIMPOS})])
    r = _rodar(prov, monkeypatch, body=_body_irb(fx))
    assert r.success, r.erros
    assert r.rodadas == 1 and r.campos["bullets[0]"] == _SLOTS_LIMPOS["bullets[0]"]


def test_11c_o_retry_conserta_a_data_inventada(monkeypatch):
    fx = _irb()
    real = _emissao_irb(fx, _campos_irb(fx))
    limpa = _emissao_irb(fx, {**_campos_irb(fx), **_SLOTS_LIMPOS})
    prov = _Prov([_FIM], [real, limpa])
    r = _rodar(prov, monkeypatch, body=_body_irb(fx))
    assert r.success and r.rodadas == 2, r.erros
    assert r.campos["ultima_ocorrencia.texto"] == _SLOTS_LIMPOS["ultima_ocorrencia.texto"]


def test_11d_datas_em_formatos_diferentes_casam():
    from src.agents.ficha_writer.validacao import FontesDeFato

    for fonte in ("Sessão de 01/09/2026.", "data: 2026-09-01T10:00:00Z",
                  "Sessão de 1º de setembro de 2026.", "Sessão de 01.09.2026."):
        f = FontesDeFato.montar(textos_docs=[fonte])
        for texto in ("em 01/09/2026", "em 1º de setembro de 2026", "em 1/9/2026",
                      "em 2026-09-01", "em 09/2026"):
            assert f.sem_fonte(texto) == [], (fonte, texto)
    f = FontesDeFato.montar(textos_docs=["Sessão de 17/06/2026."])
    assert f.sem_fonte("em 01/09/2026 e 17/06/2026") == ["01/09/2026"]
    assert f.sem_fonte("de 01/2015 a 06/2026") == ["01/2015"]


def test_11e_numeros_e_valores_casam_normalizados():
    from src.agents.ficha_writer.validacao import FontesDeFato

    f = FontesDeFato.montar(
        textos_docs=["Decisao_16327721182201921_3102-004203.PDF",
                     "CDA 80 6 10 010169-09, exigência de R$ 35.773.520,56"],
        estruturados=[{"valor_garantia": 182787942.5}],
    )
    ok = ("acórdão 3102-004.203, CDA 80610010169-09, PA 16327.721182/2019-21, "
          "R$ 35.773.520,56, R$ 182,8 milhões e R$ 183 milhões")
    assert f.sem_fonte(ok) == []
    ruim = "acórdão 3102-004.204, CDA 80 6 10 010169-08, R$ 190 milhões"
    assert f.sem_fonte(ruim) == ["3102-004.204", "80 6 10 010169-08", "R$ 190 milhões"]


def test_11f_esgotamento_vale_com_a_etapa_concluida_ou_com_a_decisao():
    from src.agents.ficha_writer.validacao import FontesDeFato

    texto = "A via administrativa está esgotada e o REsp não foi admitido."
    aberto = [{"etapa": "CARF", "status": "concluido_desfavoravel"},
              {"etapa": "CSRF", "status": "em_andamento"}]
    fechado = [{"etapa": "CARF", "status": "concluido_desfavoravel"},
               {"etapa": "Cobrança", "status": "em_andamento"}]
    assert FontesDeFato.montar(pipeline=aberto).esgotamento_sem_fonte(texto)
    assert FontesDeFato.montar(pipeline=fechado).esgotamento_sem_fonte(texto) == []
    decisao = FontesDeFato.montar(pipeline=aberto,
                                  textos_docs=["Nego seguimento ao recurso especial."])
    assert decisao.esgotamento_sem_fonte(texto) == []
    # Trânsito: só com a etapa judicial concluída ou com "transitado em julgado".
    assert FontesDeFato.montar(pipeline=fechado).esgotamento_sem_fonte("Houve trânsito.")
    assert FontesDeFato.montar(
        textos_docs=["A sentença transitou em julgado."]).esgotamento_sem_fonte(
        "Houve trânsito.") == []


# ── (12) o histórico de erros por rodada e a versão (24/10/2026) ───────────
# O `S4.json` só trazia o nº de rodadas e os erros da última. Um fato sem fonte que
# uma rodada corrigiu não deixava rastro. O debugger visual lê `rodadas_detalhe`.


def test_12a_rodadas_detalhe_guarda_os_erros_de_cada_rodada(monkeypatch):
    sem_trilha = _emissao(trilha=[_trilha_ok()[1]])
    so_merito = {"merito.p1": _CAMPOS["merito.p1"]}
    sem_json = "isto não é JSON"
    ok = _emissao(campos=so_merito, trilha=[_trilha_ok()[0]], alertas=[])
    prov = _Prov(_leituras(), [sem_trilha, sem_json, ok])
    r = _rodar(prov, monkeypatch)
    assert r.success, r.erros
    assert r.rodadas == 3
    assert r.versao == "ficha_writer_v5" and r.modo == "v5"
    d = r.rodadas_detalhe
    assert [x.rodada for x in d] == [1, 2, 3]
    # Rodada 1: o mérito reprovou por falta de trilha. O bullet passou.
    assert [e.campo for e in d[0].erros] == ["merito.p1"]
    assert "slot sem trilha_leitura" in d[0].erros[0].erro
    assert d[0].erros[0].valor_anterior == _CAMPOS["merito.p1"]
    assert set(d[0].slots_pedidos) == {"merito.p1", "bullets[0]"}
    assert set(d[0].slots_devolvidos) == {"merito.p1", "bullets[0]"}
    # Rodada 2: a saída não é JSON. O retry pediu só o mérito.
    assert [e.campo for e in d[1].erros] == ["_saida"]
    assert "parse do JSON" in d[1].erros[0].erro
    assert d[1].slots_pedidos == ["merito.p1"] and d[1].slots_devolvidos == []
    # Rodada 3: aprovada, com `erros=[]`.
    assert d[2].erros == [] and d[2].slots_devolvidos == ["merito.p1"]
    dump = r.model_dump()
    assert dump["rodadas_detalhe"][0]["erros"][0]["campo"] == "merito.p1"


def test_12b_o_v4_aceita_a_resposta_sem_versao_e_sem_modo():
    from src.agents.ficha_writer.schemas import FichaWriteFieldsResponse

    r = FichaWriteFieldsResponse(success=True)
    assert r.versao is None and r.modo is None and r.rodadas_detalhe == []
    r4 = FichaWriteFieldsResponse(success=True, versao="ficha_writer_v4", modo="v4")
    assert r4.versao == "ficha_writer_v4" and r4.modo == "v4"

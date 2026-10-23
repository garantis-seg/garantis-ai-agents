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
    ({"doc_id": "carf:impugnacao.pdf", "paginas": [1],
      "trecho_apoio": "Impugnação ao auto de infração de PIS."}, "não foi lido na fase A"),
    ({"doc_id": "carf:recurso.pdf", "paginas": [2],
      "trecho_apoio": "O recurso especial foi admitido."}, "não está, literal"),
    ({"doc_id": "carf:recurso.pdf", "paginas": [9], "trecho_apoio": _TRECHO_RECURSO},
     "página que não existe"),
    ({"doc_id": "carf:acordao.pdf", "paginas": [],
      "trecho_apoio": "O CARF cancelou a exigência."}, "não está, literal"),
], ids=["fora_do_indice", "nao_lido", "trecho_inventado", "pagina_inexistente",
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

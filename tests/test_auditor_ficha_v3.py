"""Auditor de ficha (S6) v3: o auditor que abre os autos para refutar. Sem rede.

Decisão do Alfredo de 23/10/2026: "núcleo obrigatório + índice navegável; o
auditor vira v3 como agente". O provider é um dublê que separa as fases pelo
`response_mime_type`. O Leitor é um dublê injetado.

ANTI-VACUIDADE: cada teste de regra dura exige o efeito no campo certo (item
movido de balde, erro no campo da prova, veredito calculado pelo código).
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from garantis_shared.llm_models import model_for
from pydantic import ValidationError

import src.agents.auditor_ficha.agent as agent_mod
import src.agents.auditor_ficha.agent_v3 as v3_mod
from src.agents.auditor_ficha import auditar_ficha
from src.agents.auditor_ficha.agent_v3 import BUDGET_POR_FICHA, auditar_ficha_v3
from src.agents.auditor_ficha.prompts import PROMPT_VERSION as PROMPT_V2
from src.agents.auditor_ficha.schemas import (
    AuditarFichaRequest,
    FatoConferido,
    SaidaAuditorV3,
)
from src.api.routes.auditor_ficha import router
from tests.test_auditor_ficha import _FakeProvider, _req
from tests.test_ficha_writer_v5 import (
    _ACORDAO,
    _TRECHO_NUCLEO,
    _TRECHO_RECURSO,
    _FIM,
    _Prov,
    _indice,
    _leitor,
    _nucleo,
    _tool,
)

# ── Request ─────────────────────────────────────────────────────────────────


def _trilha() -> list[dict]:
    return [
        {"slot": "merito.p1", "doc_id": "carf:acordao.pdf", "paginas": [],
         "trecho_apoio": _TRECHO_NUCLEO},
        {"slot": "bullets[0]", "doc_id": "carf:recurso.pdf", "paginas": [2],
         "trecho_apoio": "O recurso especial foi admitido em 01/09/2026."},
    ]


def _body(**over: Any) -> dict:
    body = {
        "ficha": {
            "processo_id": "16327.721182/2019-21",
            "merito": {"p1": "O CARF manteve PIS e COFINS sobre receitas financeiras."},
            "bullets": ["O recurso especial foi admitido em 01/09/2026."],
        },
        "esqueleto": {"processo_id": "16327.721182/2019-21", "etapa_atual": "CARF"},
        "dossie": "Acórdão 3102-004.203, sessão de 17/06/2026.",
        "tipo_ficha": "nova_apolice",
        "trilho": "carf",
        "alertas": [{"codigo": "AL1", "texto": "O valor é estimado."}],
        "nucleo": _nucleo(),
        "indice_navegavel": _indice(),
        "trilha_leitura": _trilha(),
    }
    body.update(over)
    return body


# ── Saídas do modelo ────────────────────────────────────────────────────────

_PROVA_RECURSO = {"doc_id": "carf:recurso.pdf", "pagina": 2, "trecho": _TRECHO_RECURSO}


def _b1(**over: Any) -> dict:
    item = {"campo": "bullets[0]", "motivo": "o REsp não foi admitido, diz o despacho",
            "regra": "D-01", "correcao_sugerida": "REsp não admitido em 01/09/2026",
            "prova": _PROVA_RECURSO, "sem_prova_no_doc": False}
    item.update(over)
    return item


def _fatos(confere_bullet: bool = False) -> list[dict]:
    return [
        {"slot": "merito.p1", "doc_id": "carf:acordao.pdf", "confere": True,
         "motivo": "o acórdão manteve a exigência"},
        {"slot": "bullets[0]", "doc_id": "carf:recurso.pdf", "confere": confere_bullet,
         "motivo": "o despacho diz não admitido"},
    ]


def _saida(**over: Any) -> dict:
    s = {"balde1": [_b1()], "balde2": [], "nao_confirmado": [],
         "alertas_respondidos": [{"codigo": "AL1", "resposta": "confirmado", "motivo": "ok"}],
         "divergencias_gabarito": [], "fatos_conferidos": _fatos()}
    s.update(over)
    return s


def _ler_recurso() -> list[str]:
    return [_tool("perguntar_ao_documento", "carf:recurso.pdf"), _FIM]


def _rodar(prov: _Prov, monkeypatch, body: dict | None = None, leitor=None):
    monkeypatch.setattr(v3_mod, "create_provider", lambda *_a, **_k: prov)
    leitor = leitor or _leitor(["fl2-s1"])
    req = AuditarFichaRequest(**(body or _body()))
    return asyncio.run(auditar_ficha_v3(req, "gemini", None, leitor_perguntar=leitor,
                                        leitor_resumir=leitor))


# ── (1) o auditor refuta com prova ─────────────────────────────────────────


def test_1_auditor_le_e_refuta_com_prova(monkeypatch):
    leitor = _leitor(["fl2-s1"])
    prov = _Prov(_ler_recurso(), [_saida()])
    r = _rodar(prov, monkeypatch, leitor=leitor)

    assert r.success and r.auditor_enabled
    assert r.veredito == "aprovada_com_correcoes" and r.aprovado is True
    [item] = r.model_dump()["balde1"]
    assert item["campo"] == "bullets[0]" and item["prova"] == _PROVA_RECURSO
    assert r.reprovacoes == [{"campo": "bullets[0]", "motivo": item["motivo"], "regra": "D-01"}]
    assert [f.confere for f in r.fatos_conferidos] == [True, False]
    assert r.documentos_lidos == ["carf:recurso.pdf"] and r.chamadas_ferramenta == 1
    assert r.prompt_version.startswith("auditor_ficha_v3+")
    assert leitor.chamadas[0]["doc_id"] == "carf:recurso.pdf"
    assert all("response_mime_type" not in c for c in prov.chamadas if c["_fase"] == "A")


def test_1b_prompt_leva_trilha_nucleo_indice_e_nao_leva_gabarito(monkeypatch):
    prov = _Prov(_ler_recurso(), [_saida()])
    _rodar(prov, monkeypatch)
    for p in (prov.prompts("A")[0], prov.prompts("B")[0]):
        assert _ACORDAO in p
        assert "TRILHA DE LEITURA DO REDATOR" in p
        assert "O recurso especial foi admitido em 01/09/2026." in p
        assert "carf:impugnacao.pdf" in p
        assert "GABARITO (FATOS ESPERADOS" not in p
    b = prov.prompts("B")[0]
    assert "<regras_de_prova>" in b and _TRECHO_RECURSO in b
    assert b.rstrip().endswith("</regra_de_decisao>")


def test_1c_rota_responde_v3(monkeypatch):
    import src.agents.ficha_writer.ferramentas as ferr_mod

    prov = _Prov(_ler_recurso(), [_saida()])
    monkeypatch.setattr(v3_mod, "create_provider", lambda *_a, **_k: prov)
    leitor = _leitor(["fl2-s1"])
    monkeypatch.setattr(ferr_mod, "perguntar_via_doc_reader", leitor)
    monkeypatch.setattr(ferr_mod, "resumir_via_doc_reader", leitor)
    app = FastAPI()
    app.include_router(router)
    resp = TestClient(app).post("/ficha/auditar", json=_body())
    assert resp.status_code == 200
    j = resp.json()
    assert j["success"] is True and j["veredito"] == "aprovada_com_correcoes"
    assert j["balde1"][0]["prova"] == _PROVA_RECURSO
    assert j["fatos_conferidos"][1]["confere"] is False


# ── (2) contradito sem prova vai ao balde 2 com grau media ─────────────────


def test_2_contradito_sem_prova_vai_ao_balde_2_media(monkeypatch):
    sem = _b1(prova=None, sem_prova_no_doc=True)
    prov = _Prov(_ler_recurso(), [_saida(balde1=[sem])])
    r = _rodar(prov, monkeypatch)
    assert r.success
    assert r.balde1 == []
    [p] = r.balde2
    assert p.campo == "bullets[0]" and p.grau == "media"
    assert p.model_dump()["sem_prova_no_doc"] is True
    assert r.veredito == "aprovada"         # balde 2 media não retém
    assert r.reprovacoes == []
    assert any("balde 2 · media" in x for x in r.pendencias)


def test_2b_balde_2_alta_com_prova_retem(monkeypatch):
    b2 = {"campo": "pipeline", "pendencia": "esgotamento duvidoso", "grau": "alta",
          "evidencia": "despacho", "recomendacao": "conferir", "prova": _PROVA_RECURSO,
          "sem_prova_no_doc": False}
    prov = _Prov(_ler_recurso(), [_saida(balde2=[b2])])
    r = _rodar(prov, monkeypatch)
    assert r.veredito == "retida" and r.aprovado is False


# ── (3) a prova é conferida pelo código ────────────────────────────────────


@pytest.mark.parametrize(("prova", "erro"), [
    ({"doc_id": "carf:nao-existe.pdf", "pagina": 1, "trecho": "x"}, "fora do núcleo e do índice"),
    # 23/10/2026: o código abre o documento não lido. Sem conteúdo indexado, reprova.
    ({"doc_id": "carf:anexo.pdf", "pagina": 1, "trecho": "Anexo."},
     "não foi lido na fase A, e o código não consegue abrir"),
    ({"doc_id": "carf:recurso.pdf", "pagina": 2, "trecho": "O REsp foi provido."},
     "não está no documento citado"),
    ({"doc_id": "carf:impugnacao.pdf", "pagina": 1, "trecho": "O REsp foi provido."},
     "o código abriu o documento, e o trecho não está nele"),
], ids=["fora", "nao_lido_ilegivel", "inventado", "nao_lido_sem_trecho"])
def test_3_prova_invalida_pede_correcao_e_depois_falha(monkeypatch, prova, erro):
    prov = _Prov(_ler_recurso(), [_saida(balde1=[_b1(prova=prova)])])
    r = _rodar(prov, monkeypatch)
    assert r.success is False and r.auditor_enabled is False and r.veredito is None
    assert r.rodadas == 2
    assert {e["campo"] for e in r.erros_validacao} == {"balde1[0].prova"}
    assert erro in r.erros_validacao[0]["erro"]
    assert "CORRECAO (422" in prov.prompts("B")[1]
    assert r.prompt_version.startswith("auditor_ficha_v3+")


def test_3b_prova_corrigida_na_2a_rodada_passa(monkeypatch):
    ruim = _saida(balde1=[_b1(prova={**_PROVA_RECURSO, "trecho": "inventado"})])
    prov = _Prov(_ler_recurso(), [ruim, _saida()])
    r = _rodar(prov, monkeypatch)
    assert r.success and r.rodadas == 2 and r.veredito == "aprovada_com_correcoes"


def test_3c_prova_do_nucleo_nao_exige_ferramenta(monkeypatch):
    b1 = _b1(campo="merito.p1", prova={"doc_id": "carf:acordao.pdf", "pagina": 1,
                                        "trecho": "por maioria"})
    fatos = [{**_fatos()[0], "confere": False}, {**_fatos()[1], "confere": True}]
    prov = _Prov([_FIM], [_saida(balde1=[b1], fatos_conferidos=fatos)])
    r = _rodar(prov, monkeypatch)
    assert r.success, r.erros_validacao
    assert r.chamadas_ferramenta == 0


@pytest.mark.parametrize("item", [
    _b1(prova=None, sem_prova_no_doc=False),
    _b1(sem_prova_no_doc=True),
], ids=["nenhum", "os_dois"])
def test_3d_item_sem_prova_nem_marca_e_erro_de_schema(monkeypatch, item):
    prov = _Prov(_ler_recurso(), [_saida(balde1=[item])])
    r = _rodar(prov, monkeypatch)
    assert r.success is False
    assert any(e["campo"].startswith("balde1.0") for e in r.erros_validacao)


# ── (4) fatos conferidos ───────────────────────────────────────────────────


def test_4_slot_da_trilha_sem_conferencia_e_erro(monkeypatch):
    prov = _Prov(_ler_recurso(), [_saida(fatos_conferidos=_fatos()[1:])])
    r = _rodar(prov, monkeypatch)
    assert r.success is False
    assert "o slot merito.p1 da trilha nao foi conferido" in r.erros_validacao[0]["erro"]


def test_4b_confere_false_sem_item_no_balde_e_erro(monkeypatch):
    prov = _Prov(_ler_recurso(), [_saida(balde1=[])])
    r = _rodar(prov, monkeypatch)
    assert r.success is False
    assert "confere=false sem item" in r.erros_validacao[0]["erro"]


def test_4c_fato_com_doc_fora_dos_autos_e_erro(monkeypatch):
    fatos = [_fatos()[0], {**_fatos()[1], "doc_id": "carf:outro.pdf"}]
    prov = _Prov(_ler_recurso(), [_saida(fatos_conferidos=fatos)])
    r = _rodar(prov, monkeypatch)
    assert r.success is False
    assert r.erros_validacao[0]["campo"] == "fatos_conferidos[1].doc_id"


# ── (5) gabarito nunca entra no v3 ─────────────────────────────────────────


def test_5_v3_recusa_gabarito():
    with pytest.raises(ValidationError, match="nunca recebe gabarito"):
        AuditarFichaRequest(**_body(gabarito={"merito": {"p1": "x"}}))


def test_5b_rota_devolve_422_com_gabarito():
    app = FastAPI()
    app.include_router(router)
    resp = TestClient(app).post("/ficha/auditar", json=_body(gabarito={"x": 1}))
    assert resp.status_code == 422


def test_5c_meio_v3_e_rejeitado():
    body = _body()
    del body["indice_navegavel"]
    with pytest.raises(ValidationError, match="juntos"):
        AuditarFichaRequest(**body)


def test_5d_divergencia_de_gabarito_no_v3_e_erro(monkeypatch):
    div = [{"campo": "x", "ficha": "a", "gabarito": "b", "e_erro": False, "motivo": "m"}]
    prov = _Prov(_ler_recurso(), [_saida(divergencias_gabarito=div)])
    r = _rodar(prov, monkeypatch)
    assert r.success is False
    assert r.erros_validacao[0]["campo"] == "divergencias_gabarito"


# ── (6) budget ─────────────────────────────────────────────────────────────


def test_6_budget_de_20_por_ficha(monkeypatch):
    def decide(i: int) -> str:
        doc = ("carf:recurso.pdf", "carf:impugnacao.pdf")[i % 2]
        return _tool("perguntar_ao_documento", doc)

    leitor = _leitor(["fl1-s1"])
    prov = _Prov(decide, [_saida(balde1=[_b1(prova=None, sem_prova_no_doc=True)])])
    r = _rodar(prov, monkeypatch, leitor=leitor)
    assert BUDGET_POR_FICHA == 20
    assert r.budget_esgotado is True and r.chamadas_ferramenta == 20
    assert len(leitor.chamadas) == 10                       # 5 por documento
    assert r.success


# ── (7) compatibilidade: o v2 segue igual com o request antigo ─────────────


def test_7_request_v2_segue_v2(monkeypatch):
    prov = _FakeProvider(json.dumps({"balde1": [{"campo": "ultima_decisao.texto",
                                                 "motivo": "data errada", "regra": "D-01"}]}))
    monkeypatch.setattr(agent_mod, "create_provider", lambda p: prov)
    r = asyncio.run(auditar_ficha(_req()))
    assert r.success and r.prompt_version == PROMPT_V2
    assert len(prov.chamadas) == 1
    assert "response_mime_type" in prov.chamadas[0]
    item = r.model_dump()["balde1"][0]
    assert "prova" not in item and "sem_prova_no_doc" not in item
    assert r.fatos_conferidos == [] and r.chamadas_ferramenta == 0


def test_7b_saida_v2_com_prova_continua_recusada():
    """O schema do v2 segue fechado: a chave `prova` do v3 não vaza para o v2."""
    from src.agents.auditor_ficha.schemas import SaidaAuditor

    with pytest.raises(ValidationError):
        SaidaAuditor.model_validate({"balde1": [_b1()]})


# ── (8) schemas fechados ───────────────────────────────────────────────────


@pytest.mark.parametrize(("modelo", "dados"), [
    (SaidaAuditorV3, {**_saida(), "extra": 1}),
    (SaidaAuditorV3, {**_saida(), "balde1": [{**_b1(), "nota": "x"}]}),
    (SaidaAuditorV3, {**_saida(), "balde1": [_b1(prova={**_PROVA_RECURSO, "linha": 3})]}),
    (FatoConferido, {**_fatos()[0], "pagina": 1}),
], ids=["saida", "item", "prova", "fato"])
def test_8_schemas_rejeitam_chave_extra(modelo, dados):
    with pytest.raises(ValidationError):
        modelo.model_validate(dados)


def test_8b_request_v3_com_chave_extra_e_422():
    app = FastAPI()
    app.include_router(router)
    resp = TestClient(app).post("/ficha/auditar", json=_body(gabarito_v3={"x": 1}))
    assert resp.status_code == 422


# ── (9) modelo do papel ────────────────────────────────────────────────────


def test_9_o_v3_usa_o_papel_ficha_auditoria_texto(monkeypatch):
    prov = _Prov(_ler_recurso(), [_saida()])
    r = _rodar(prov, monkeypatch)
    assert v3_mod.DEFAULT_MODEL == model_for("ficha_auditoria_texto")
    assert {c["model"] for c in prov.chamadas} == {model_for("ficha_auditoria_texto")}
    assert r.modelo == model_for("ficha_auditoria_texto")


# ── contrato com o shared 1.826 (23/10/2026) ───────────────────────────────


def test_contrato_nucleo_do_shared_1826_valida_sem_erro(caplog):
    from tests.test_ficha_writer_v5 import _shared_1826

    real = _shared_1826()
    with caplog.at_level("WARNING"):
        req = AuditarFichaRequest(**_body(nucleo=real["nucleo"],
                                          indice_navegavel=real["indice_navegavel"]))
    assert "FICHA_NUCLEO_CHAVE_IGNORADA" not in caplog.text
    assert req.modo_v3
    assert req.nucleo.cdas.divida_ativa["data"] == "22/10/2026"
    assert req.nucleo.metadados["conexo_id"] == 1481420
    assert req.nucleo.documentos()[0].papel == "decisao_pa"
    assert req.indice_navegavel[0].marca is None



# ── (9) determinismo máximo nas provas (23/10/2026) ────────────────────────
#
# O mesmo tratamento do redator v5: o código corta o trecho, acha a página e abre
# o documento não lido antes de reprovar a prova.


def test_9a_prova_com_trecho_acima_de_300_e_cortada_e_aceita(monkeypatch):
    from tests.test_ficha_writer_v5 import _LONGO_NUCLEO, _nucleo_longo

    longo = _LONGO_NUCLEO + " " + _LONGO_NUCLEO
    assert len(longo) > 300
    b1 = _b1(campo="merito.p1", prova={"doc_id": "carf:acordao.pdf", "pagina": 1,
                                        "trecho": longo})
    prov = _Prov(_ler_recurso(), [_saida(balde1=[b1], fatos_conferidos=[
        {**_fatos()[0], "confere": False}, {**_fatos()[1], "confere": True}])])
    r = _rodar(prov, monkeypatch, body=_body(nucleo=_nucleo_longo()))
    assert r.success, r.erros_validacao
    trecho = r.balde1[0].prova.trecho
    assert len(trecho) <= 300 and longo.startswith(trecho)


@pytest.mark.parametrize("pagina", [None, 0, "x"], ids=["nula", "zero", "texto"])
def test_9b_prova_do_nucleo_sem_pagina_e_aceita(monkeypatch, pagina):
    prova = {"doc_id": "carf:acordao.pdf", "trecho": "por maioria"}
    if pagina is not None:
        prova["pagina"] = pagina
    b1 = _b1(campo="merito.p1", prova=prova)
    prov = _Prov(_ler_recurso(), [_saida(balde1=[b1], fatos_conferidos=[
        {**_fatos()[0], "confere": False}, {**_fatos()[1], "confere": True}])])
    r = _rodar(prov, monkeypatch)
    assert r.success, r.erros_validacao
    assert r.balde1[0].prova.pagina == 1


@pytest.mark.parametrize("pagina", [None, 1, 9], ids=["sem", "errada", "inexistente"])
def test_9c_o_codigo_acha_a_pagina_da_prova_do_indice(monkeypatch, pagina):
    prova = {"doc_id": "carf:recurso.pdf", "trecho": _TRECHO_RECURSO}
    if pagina is not None:
        prova["pagina"] = pagina
    prov = _Prov(_ler_recurso(), [_saida(balde1=[_b1(prova=prova)])])
    r = _rodar(prov, monkeypatch)
    assert r.success, r.erros_validacao
    assert r.balde1[0].prova.pagina == 2


def test_9d_prova_de_documento_nao_lido_o_codigo_abre_e_aceita(monkeypatch):
    prova = {"doc_id": "carf:impugnacao.pdf", "pagina": 1,
             "trecho": "Impugnação ao auto de infração de PIS."}
    prov = _Prov([_FIM], [_saida(balde1=[_b1(prova=prova)])])
    r = _rodar(prov, monkeypatch)
    assert r.success, r.erros_validacao
    assert r.documentos_lidos == []
    assert r.balde1[0].prova.doc_id == "carf:impugnacao.pdf"


def test_9e_prova_nao_verificavel_da_a_lista_de_citaveis(monkeypatch):
    prova = {"doc_id": "carf:anexo.pdf", "pagina": 1, "trecho": "Anexo."}
    prov = _Prov(_ler_recurso(), [_saida(balde1=[_b1(prova=prova)])])
    r = _rodar(prov, monkeypatch)
    assert r.success is False
    assert ('Cite só documentos desta lista: ["carf:acordao.pdf", "carf:recurso.pdf"]'
            in r.erros_validacao[0]["erro"])
    assert "carf:recurso.pdf" in prov.prompts("B")[1]


# ── (10) a conferência do trecho normaliza o texto de PDF (23/10/2026) ─────────
#
# A mesma função dona do redator v5 (`ferramentas.trecho_confere`). O caso real é o
# do IRB 1481420: o cabeçalho de página corta a frase do voto de qualidade.


def _b1_irb(trecho: str) -> dict:
    return _b1(campo="merito.p1", prova={"doc_id": "carf:acordao.pdf", "trecho": trecho})


def _fatos_irb() -> list[dict]:
    return [{**_fatos()[0], "confere": False}, {**_fatos()[1], "confere": True}]


def test_10a_prova_com_o_trecho_real_do_irb_e_aceita(monkeypatch):
    from tests.test_ficha_writer_v5 import _TRECHO_IRB, _nucleo_irb

    prov = _Prov(_ler_recurso(), [_saida(balde1=[_b1_irb(_TRECHO_IRB)],
                                         fatos_conferidos=_fatos_irb())])
    r = _rodar(prov, monkeypatch, body=_body(nucleo=_nucleo_irb()))
    assert r.success, r.erros_validacao
    assert r.balde1[0].prova.trecho == _TRECHO_IRB


def test_10b_prova_com_a_decisao_invertida_reprova(monkeypatch):
    from tests.test_ficha_writer_v5 import _TRECHO_IRB, _nucleo_irb

    ruim = _saida(balde1=[_b1_irb(_TRECHO_IRB.replace("negar-lhe", "dar-lhe"))],
                  fatos_conferidos=_fatos_irb())
    prov = _Prov(_ler_recurso(), [ruim] * 3)
    r = _rodar(prov, monkeypatch, body=_body(nucleo=_nucleo_irb()))
    assert r.success is False
    assert "o trecho não está no documento citado" in r.erros_validacao[0]["erro"]


# ── (11) contradição com o esqueleto é balde 1, e D-FONTE (23/10/2026) ───────
#
# Rodada real do IRB 1481420 (rev 00413): o auditor v3 viu que 4 slots contradiziam
# o esqueleto (CSRF `em_andamento`) e pôs os 4 no balde 2, sem prova de documento. A
# ficha saiu aprovada com a data inventada 01/09/2026. A fixture traz a ficha real e
# os 4 itens reais do balde 2. O shared real não mandou a trilha do redator.


def _body_irb(fx: dict, **over: Any) -> dict:
    body = {
        "ficha": fx["ficha"], "esqueleto": fx["ficha"], "dossie": "",
        "tipo_ficha": fx["tipo_ficha"], "trilho": fx["trilho"],
        "alertas": [{"codigo": a["codigo"], "texto": a["texto"]} for a in fx["alertas"]],
        "nucleo": fx["nucleo"], "indice_navegavel": fx["indice_navegavel"],
    }
    body.update(over)
    return body


def _fatos_da_ficha_irb(fx: dict) -> list[dict]:
    from src.agents.ficha_writer.prompts_v5 import exige_trilha
    from src.agents.ficha_writer.validacao import slots_de_texto

    doc = fx["nucleo"]["documentos"][0]["doc_id"]
    return [{"slot": s, "doc_id": doc, "confere": True, "motivo": "o acórdão sustenta"}
            for s, t in slots_de_texto(fx["ficha"]).items() if exige_trilha(s) and t]


def _saida_irb(fx: dict, **over: Any) -> dict:
    s = {"balde1": [], "balde2": fx["auditoria_s6"]["balde2"], "nao_confirmado": [],
         "alertas_respondidos": [{"codigo": a["codigo"], "resposta": "confirmado",
                                  "motivo": "ok"} for a in fx["alertas"]],
         "divergencias_gabarito": [], "fatos_conferidos": _fatos_da_ficha_irb(fx)}
    s.update(over)
    return s


def _irb() -> dict:
    from tests.test_ficha_writer_v5 import _irb as carregar

    return carregar()


def test_11a_contradicao_com_o_esqueleto_vai_ao_balde_1_e_retem_a_aprovacao(monkeypatch):
    fx = _irb()
    assert fx["auditoria_s6"]["veredito"] == "aprovada"     # o defeito real
    prov = _Prov([_FIM], [_saida_irb(fx)])
    r = _rodar(prov, monkeypatch, body=_body_irb(fx))

    assert r.success, r.erros_validacao
    assert r.balde2 == []
    esq = [i for i in r.balde1 if i.regra == "T-01"]
    assert {i.campo for i in esq} == {"processo_administrativo.resumo",
                                      "ultima_ocorrencia.texto", "bullets[0]", "merito.p2"}
    assert all(i.model_dump()["contradiz_esqueleto"] is True for i in esq)
    assert r.veredito == "aprovada_com_correcoes"
    assert {x["campo"] for x in r.reprovacoes} >= {i.campo for i in esq}


def test_11b_o_codigo_emite_d_fonte_antes_do_llm(monkeypatch):
    fx = _irb()
    prov = _Prov([_FIM], [_saida_irb(fx, balde2=[])])
    r = _rodar(prov, monkeypatch, body=_body_irb(fx))

    assert r.success, r.erros_validacao
    d = [i for i in r.balde1 if i.regra == "D-FONTE"]
    data = {i.campo for i in d if i.motivo.startswith("fato sem fonte: 01/09/2026")}
    assert data == {"ultima_ocorrencia.texto", "bullets[0]", "merito.p2"}
    esgot = {i.campo for i in d if i.motivo.startswith("afirmação de esgotamento sem fonte")}
    assert esgot == {"processo_administrativo.resumo", "ultima_ocorrencia.texto",
                     "bullets[0]", "merito.p2"}
    assert r.veredito == "aprovada_com_correcoes"
    # O LLM recebe os achados do código no prompt do veredito.
    b = prov.prompts("B")[0]
    assert "ACHADOS DO CODIGO" in b and "01/09/2026" in b
    assert b.rstrip().endswith("</regra_de_decisao>")


def test_11c_ficha_limpa_nao_tem_d_fonte(monkeypatch):
    from tests.test_ficha_writer_v5 import _SLOTS_LIMPOS

    fx = _irb()
    ficha = json.loads(json.dumps(fx["ficha"]))
    ficha["processo_administrativo"]["resumo"] = _SLOTS_LIMPOS["processo_administrativo.resumo"]
    ficha["ultima_ocorrencia"]["texto"] = _SLOTS_LIMPOS["ultima_ocorrencia.texto"]
    ficha["bullets"][0] = _SLOTS_LIMPOS["bullets[0]"]
    ficha["merito"]["p2"] = _SLOTS_LIMPOS["merito.p2"]
    fx["ficha"] = ficha
    prov = _Prov([_FIM], [_saida_irb(fx, balde2=[])])
    r = _rodar(prov, monkeypatch, body=_body_irb(fx))
    assert r.success, r.erros_validacao
    assert r.balde1 == [] and r.veredito == "aprovada"


def test_11d_fatos_conferidos_sai_sempre(monkeypatch):
    fx = _irb()
    # Sem a chave: o schema recusa, e o retry não conserta -> "não auditada".
    sem = _saida_irb(fx)
    sem.pop("fatos_conferidos")
    prov = _Prov([_FIM], [sem] * 3)
    r = _rodar(prov, monkeypatch, body=_body_irb(fx))
    assert r.success is False
    assert any(e["campo"] == "fatos_conferidos" for e in r.erros_validacao)
    # Sem trilha do redator, cada slot de mérito, decisão, infração e bullet é conferido.
    prov = _Prov([_FIM], [_saida_irb(fx, fatos_conferidos=_fatos_da_ficha_irb(fx)[:1])] * 3)
    r = _rodar(prov, monkeypatch, body=_body_irb(fx))
    assert r.success is False
    assert any("merito.p2 da ficha (sem trilha do redator) nao foi conferido" in e["erro"]
               for e in r.erros_validacao)
    # Com todos os slots: sai na resposta e na rota.
    prov = _Prov([_FIM], [_saida_irb(fx)])
    r = _rodar(prov, monkeypatch, body=_body_irb(fx))
    assert r.success and len(r.fatos_conferidos) == len(_fatos_da_ficha_irb(fx))
    assert "fatos_conferidos" in r.model_dump()


def test_11e_a_marca_contradiz_esqueleto_manda_ao_balde_1_so_em_slot_de_texto(monkeypatch):
    marcado = {"campo": "bullets[0]", "pendencia": "a data diverge", "grau": "media",
               "evidencia": "-", "recomendacao": "conferir", "prova": None,
               "sem_prova_no_doc": True, "contradiz_esqueleto": True}
    no_pipeline = {**marcado, "campo": "pipeline", "pendencia": "o CSRF parece encerrado"}
    prov = _Prov(_ler_recurso(), [_saida(balde1=[], balde2=[marcado, no_pipeline],
                                         fatos_conferidos=_fatos(confere_bullet=True))])
    r = _rodar(prov, monkeypatch)
    assert r.success, r.erros_validacao
    assert [(i.campo, i.regra) for i in r.balde1] == [("bullets[0]", "T-01")]
    assert [i.campo for i in r.balde2] == ["pipeline"]
    # Item do balde 1 sem prova, mas que contradiz o esqueleto: fica no balde 1.
    b1 = _b1(prova=None, sem_prova_no_doc=True,
             motivo="o texto contradiz o esqueleto: a etapa CSRF está em andamento")
    prov = _Prov(_ler_recurso(), [_saida(balde1=[b1])])
    r = _rodar(prov, monkeypatch)
    assert r.success and [i.campo for i in r.balde1] == ["bullets[0]"] and r.balde2 == []

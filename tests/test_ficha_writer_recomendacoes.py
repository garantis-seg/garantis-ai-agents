"""As candidatas de `alerta` e `observacao` no redator (decisão do Alfredo).

O shared decide SE (os 15 gatilhos). O redator decide COMO, com a prova. Dois
regimes no request: `recomendacoes_candidatas` AUSENTE (o shared de hoje, nada
muda) e PRESENTE, mesmo vazia (os 2 slots só nascem para uma candidata). Sem
rede e sem LLM: o provider é um dublê.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

import src.agents.ficha_writer.agent as agent_mod
import src.agents.ficha_writer.agent_v5 as v5_mod
from src.agents.ficha_writer import write_ficha_fields
from src.agents.ficha_writer.agent_v5 import write_v5
from src.agents.ficha_writer.livro import chave_livro, resolver_slots
from src.agents.ficha_writer.prompts_v4 import build_prompt_v4
from src.agents.ficha_writer.schemas import Candidata, FichaWriteFieldsRequest
from src.agents.ficha_writer.validacao import cita_dado, validar_recomendacoes
from tests.test_ficha_writer import _esqueleto
from tests.test_ficha_writer_v5 import _Prov, _body, _emissao, _leituras, _leitor

PA_IRMAO = "16327.720083/2022-28"

_CAND_ALERTA = {
    "codigo": "voto_qualidade_multa", "slot": "alerta", "deteccao": "codigo",
    "titulo": "MULTA MANTIDA POR VOTO DE QUALIDADE",
    "molde": "O mérito foi mantido por voto de qualidade. A Lei 14.689/2023 prevê a exclusão da multa.",
    "fato": "O mérito foi mantido por voto de qualidade no acórdão 3102-004.203, sessão de 17/06/2026.",
    "datas": ["17/06/2026"], "numeros": ["3102-004.203", "14.689/2023"],
    "doc_ids": ["andamentos:16327721182201921"], "fontes": ["andamentos"], "max_chars": 250,
}
_CAND_OBS = {
    "codigo": "pa_irmao_mesma_tese", "slot": "observacao", "deteccao": "codigo",
    "molde": "Há PA irmão com a mesma tese, com o número.",
    "fato": f"PA irmão do mesmo caso: {PA_IRMAO}.", "datas": [], "numeros": [PA_IRMAO],
    "max_chars": 150,
}
_ALERTA_BOM = ("Mérito mantido por voto de qualidade em 17/06/2026 — a Lei 14.689/2023 pode"
               " excluir a multa e reduzir o valor a garantir.")
_OBS_BOA = f"O PA {PA_IRMAO} discute a mesma tese no CARF."
_CAMPOS_V4 = [
    {"nome": "bullets[0]", "path": "bullets[0]", "max": 150},
    {"nome": "alerta.texto", "path": "alerta.texto", "max": 250, "obrigatorio": False},
    {"nome": "observacao", "path": "observacao", "max": 150, "obrigatorio": False},
]
_BULLET = "Via administrativa esgotada em 01/09/2026: a empresa não tem mais recurso no CARF."


class _Seq:
    """Provider v4: devolve os textos na ordem. Guarda os prompts."""

    def __init__(self, textos: list[str | dict]):
        self.textos = list(textos)
        self.prompts: list[str] = []

    async def agenerate(self, **kw):
        self.prompts.append(kw["prompt"])
        item = self.textos[min(len(self.prompts) - 1, len(self.textos) - 1)]
        texto = item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
        return SimpleNamespace(text=texto, model=kw["model"], metadata={"cost_usd": 0.001})


def _req_v4(candidatas: Any = "ausente", **over: Any) -> dict:
    body = {
        "dossie": "Acórdão 3102-004.203, sessão de 17/06/2026.",
        "tipo_ficha": "nova_apolice", "trilho": "carf", "esqueleto": _esqueleto(),
        "campos": [dict(c) for c in _CAMPOS_V4], "alertas": [],
    }
    if candidatas != "ausente":
        body["recomendacoes_candidatas"] = candidatas
    body.update(over)
    return body


def _saida(campos: dict, rec: list | None = None) -> dict:
    out: dict[str, Any] = {"campos": campos, "alertas_respondidos": []}
    if rec is not None:
        out["recomendacoes_respondidas"] = rec
    return out


def _roda_v4(monkeypatch, body: dict, saidas: list) -> tuple[Any, _Seq]:
    prov = _Seq(saidas)
    monkeypatch.setattr(agent_mod, "create_provider", lambda *_a, **_k: prov)
    return asyncio.run(write_ficha_fields(body)), prov


_REC_OK = [{"codigo": "voto_qualidade_multa", "resposta": "redigida",
            "prova": "andamentos:16327721182201921"},
           {"codigo": "pa_irmao_mesma_tese", "resposta": "redigida", "prova": "cartão do motor"}]


# ── Schema ──────────────────────────────────────────────────────────────────

def test_schema_aceita_candidatas_e_recusa_chave_extra_e_codigo_repetido():
    req = FichaWriteFieldsRequest(**_req_v4([_CAND_ALERTA, _CAND_OBS]))
    assert req.regime_candidatas and len(req.recomendacoes_candidatas) == 2
    assert not FichaWriteFieldsRequest(**_req_v4()).regime_candidatas
    assert FichaWriteFieldsRequest(**_req_v4([])).regime_candidatas
    with pytest.raises(ValidationError):
        FichaWriteFieldsRequest(**_req_v4([{**_CAND_ALERTA, "inventado": 1}]))
    with pytest.raises(ValidationError):
        FichaWriteFieldsRequest(**_req_v4([_CAND_ALERTA, _CAND_ALERTA]))
    with pytest.raises(ValidationError):
        Candidata(**{**_CAND_ALERTA, "slot": "bullets[0]"})


# ── Regime antigo: nada muda ────────────────────────────────────────────────

def test_regime_antigo_o_prompt_nao_tem_o_bloco_e_a_resposta_sai_vazia(monkeypatch):
    body = _req_v4()
    r, prov = _roda_v4(monkeypatch, body, [_saida({"bullets[0]": _BULLET, "alerta.texto": "",
                                                    "observacao": ""})])
    assert r.success is True and r.recomendacoes_respondidas == []
    assert "<recomendacoes>" not in prov.prompts[0]
    assert "recomendacoes_respondidas" not in prov.prompts[0]


def test_regime_antigo_o_prompt_v4_fica_byte_a_byte_igual():
    """O bloco só entra com `candidatas`. Sem elas, o prompt de hoje não muda."""
    req = FichaWriteFieldsRequest(**_req_v4())
    slots, _ = resolver_slots(req, req.campos)
    a = build_prompt_v4(req, chave=chave_livro(req), slots=slots, alertas=[], citaveis=[],
                        fence_token="t0")
    b = build_prompt_v4(req, chave=chave_livro(req), slots=slots, alertas=[], citaveis=[],
                        fence_token="t0", candidatas=None)
    assert a == b and "<recomendacoes>" not in a


# ── Regime novo (v4) ────────────────────────────────────────────────────────

def test_controle_positivo_alerta_e_observacao_no_molde_passam_na_1a_rodada(monkeypatch):
    body = _req_v4([_CAND_ALERTA, _CAND_OBS])
    r, prov = _roda_v4(monkeypatch, body, [
        _saida({"bullets[0]": _BULLET, "alerta.texto": _ALERTA_BOM, "observacao": _OBS_BOA}, _REC_OK)])
    assert r.success is True, r.error
    assert r.rodadas == 1
    assert r.campos["alerta.texto"] == _ALERTA_BOM and r.campos["observacao"] == _OBS_BOA
    assert [x.model_dump() for x in r.recomendacoes_respondidas] == [
        {"codigo": "voto_qualidade_multa", "resposta": "redigida", "motivo": None,
         "prova": "andamentos:16327721182201921"},
        {"codigo": "pa_irmao_mesma_tese", "resposta": "redigida", "motivo": None,
         "prova": "cartão do motor"}]
    p = prov.prompts[0]
    assert "<recomendacoes>" in p and "[voto_qualidade_multa]" in p and "17/06/2026" in p
    # O bloco fica no fim, com as instruções, depois do dossiê.
    assert p.index("<recomendacoes>") > p.index("<dossie-")
    assert p.index("<recomendacoes>") < p.index("<regras_de_redacao>")
    assert '"recomendacoes_respondidas": [' in p


def test_candidatas_vazias_sem_slot_de_alerta_passa_e_devolve_lista_vazia(monkeypatch):
    body = _req_v4([], campos=[dict(_CAMPOS_V4[0])])
    r, prov = _roda_v4(monkeypatch, body, [_saida({"bullets[0]": _BULLET}, [])])
    assert r.success is True and r.recomendacoes_respondidas == []
    assert "CANDIDATAS DESTA FICHA: nenhuma" in prov.prompts[0]


def test_slot_cheio_sem_candidata_reprova_e_o_retry_conserta(monkeypatch):
    body = _req_v4([])
    ruim = _saida({"bullets[0]": _BULLET, "alerta.texto": "Alerta sem gatilho de 17/06/2026.",
                   "observacao": ""}, [])
    bom = _saida({"alerta.texto": ""}, [])
    r, prov = _roda_v4(monkeypatch, body, [ruim, bom])
    assert r.success is True and r.rodadas == 2
    assert "alerta.texto" not in r.campos or r.campos["alerta.texto"] == ""
    assert "sem candidata do slot alerta" in prov.prompts[1]


def test_texto_sem_a_data_nem_o_numero_reprova_com_a_lista(monkeypatch):
    body = _req_v4([_CAND_ALERTA])
    ruim = _saida({"bullets[0]": _BULLET, "alerta.texto": "O mérito foi mantido por voto de "
                   "qualidade — a multa pode cair.", "observacao": ""},
                  [{"codigo": "voto_qualidade_multa", "resposta": "redigida"}])
    bom = _saida({"alerta.texto": _ALERTA_BOM}, [{"codigo": "voto_qualidade_multa", "resposta": "redigida"}])
    r, prov = _roda_v4(monkeypatch, body, [ruim, bom])
    assert r.success is True and r.rodadas == 2
    assert "Cite 1 destes: 17/06/2026, 3102-004.203, 14.689/2023" in prov.prompts[1]
    assert r.campos["alerta.texto"] == _ALERTA_BOM


def test_candidata_sem_resposta_reprova(monkeypatch):
    body = _req_v4([_CAND_ALERTA])
    ruim = _saida({"bullets[0]": _BULLET, "alerta.texto": _ALERTA_BOM, "observacao": ""}, [])
    r, prov = _roda_v4(monkeypatch, body, [ruim, ruim, ruim])
    assert "sem resposta" in prov.prompts[1]
    # Esgotado só no slot de alerta: o slot sai, e a ficha segue (regra do dono).
    assert r.success is True and "alerta.texto" not in r.campos


def test_refutada_exige_motivo_e_o_slot_fica_vazio(monkeypatch):
    body = _req_v4([_CAND_ALERTA])
    sem_motivo = _saida({"bullets[0]": _BULLET, "alerta.texto": "", "observacao": ""},
                        [{"codigo": "voto_qualidade_multa", "resposta": "refutada"}])
    com_motivo = _saida({"bullets[0]": _BULLET, "alerta.texto": "", "observacao": ""},
                        [{"codigo": "voto_qualidade_multa", "resposta": "refutada",
                          "motivo": "O acórdão diz unanimidade (fl. 12)."}])
    r, _ = _roda_v4(monkeypatch, body, [sem_motivo, com_motivo])
    assert r.success is True and r.rodadas == 2
    assert r.recomendacoes_respondidas[0].resposta == "refutada"
    assert r.campos.get("alerta.texto", "") == ""


def test_redigida_com_slot_vazio_reprova(monkeypatch):
    body = _req_v4([_CAND_ALERTA])
    ruim = _saida({"bullets[0]": _BULLET, "alerta.texto": "", "observacao": ""},
                  [{"codigo": "voto_qualidade_multa", "resposta": "redigida"}])
    r, prov = _roda_v4(monkeypatch, body, [ruim, ruim, ruim])
    assert "marcada redigida, mas o slot está vazio" in prov.prompts[1]
    assert r.success is True and r.recomendacoes_respondidas == []


def test_observacao_que_pede_acao_reprova(monkeypatch):
    body = _req_v4([_CAND_OBS])
    ruim = _saida({"bullets[0]": _BULLET, "alerta.texto": "",
                   "observacao": f"Confira o PA {PA_IRMAO}, que discute a mesma tese."},
                  [{"codigo": "pa_irmao_mesma_tese", "resposta": "redigida"}])
    bom = _saida({"observacao": _OBS_BOA}, [{"codigo": "pa_irmao_mesma_tese", "resposta": "redigida"}])
    r, prov = _roda_v4(monkeypatch, body, [ruim, bom])
    assert r.success is True and r.rodadas == 2
    assert 'pede ação ("Confira")' in prov.prompts[1]


def test_texto_generico_de_estrategias_juridicas_reprova(monkeypatch):
    body = _req_v4([_CAND_ALERTA])
    ruim = _saida({"bullets[0]": "A companhia ainda dispõe de estratégias jurídicas.",
                   "alerta.texto": _ALERTA_BOM, "observacao": ""},
                  [{"codigo": "voto_qualidade_multa", "resposta": "redigida"}])
    bom = _saida({"bullets[0]": _BULLET}, [])
    r, prov = _roda_v4(monkeypatch, body, [ruim, bom])
    assert r.success is True and r.rodadas == 2
    assert "texto genérico proibido" in prov.prompts[1]


def test_resposta_aceita_numa_rodada_vale_na_seguinte(monkeypatch):
    """O modelo não precisa repetir a resposta da candidata no retry de outro slot."""
    body = _req_v4([_CAND_ALERTA])
    r1 = _saida({"bullets[0]": "x" * 151, "alerta.texto": _ALERTA_BOM, "observacao": ""},
                [{"codigo": "voto_qualidade_multa", "resposta": "redigida"}])
    r2 = _saida({"bullets[0]": _BULLET})
    r, _ = _roda_v4(monkeypatch, body, [r1, r2])
    assert r.success is True and r.rodadas == 2
    assert r.recomendacoes_respondidas[0].codigo == "voto_qualidade_multa"


# ── Regime novo (v5) ────────────────────────────────────────────────────────

def _body_v5(candidatas: Any) -> dict:
    body = _body(campos=[
        {"nome": "merito.p1", "path": "merito.p1", "max": 600},
        {"nome": "bullets[0]", "path": "bullets[0]", "max": 150},
        {"nome": "alerta.texto", "path": "alerta.texto", "max": 250, "obrigatorio": False},
    ])
    body["recomendacoes_candidatas"] = candidatas
    return body


def _rodar_v5(prov: _Prov, monkeypatch, body: dict):
    monkeypatch.setattr(v5_mod, "create_provider", lambda *_a, **_k: prov)
    leitor = _leitor(["fl2-s1"])
    req = FichaWriteFieldsRequest(**body)
    return asyncio.run(write_v5(req, "gemini", None, leitor_perguntar=leitor, leitor_resumir=leitor))


def test_v5_escreve_o_alerta_para_a_candidata_e_cita_a_prova(monkeypatch):
    em = _emissao()
    em["campos"]["alerta.texto"] = _ALERTA_BOM
    em["recomendacoes_respondidas"] = [{"codigo": "voto_qualidade_multa", "resposta": "redigida",
                                        "prova": "andamentos:16327721182201921"}]
    prov = _Prov(_leituras(), [em])
    r = _rodar_v5(prov, monkeypatch, _body_v5([_CAND_ALERTA]))
    assert r.success is True, r.error
    assert r.campos["alerta.texto"] == _ALERTA_BOM
    assert r.recomendacoes_respondidas[0].codigo == "voto_qualidade_multa"
    p = prov.prompts("B")[0]
    assert "<recomendacoes>" in p and p.index("<recomendacoes>") < p.index("<regras_da_trilha>")
    assert "4 chaves" in p


def test_v5_a_data_da_candidata_e_fonte_da_regra_11(monkeypatch):
    """17/06/2026 está no núcleo. 14.689/2023 só está na candidata: a candidata é fonte."""
    em = _emissao()
    em["campos"]["alerta.texto"] = "Multa mantida por voto de qualidade — a Lei 14.689/2023 pode excluí-la."
    em["recomendacoes_respondidas"] = [{"codigo": "voto_qualidade_multa", "resposta": "redigida"}]
    prov = _Prov(_leituras(), [em])
    r = _rodar_v5(prov, monkeypatch, _body_v5([_CAND_ALERTA]))
    assert r.success is True, r.error


def test_v5_sem_candidatas_segue_como_hoje(monkeypatch):
    prov = _Prov(_leituras(), [_emissao()])
    body = _body()
    r = _rodar_v5(prov, monkeypatch, body)
    assert r.success is True and r.recomendacoes_respondidas == []
    assert "<recomendacoes>" not in prov.prompts("B")[0]


# ── As funções puras ────────────────────────────────────────────────────────

@pytest.mark.parametrize("texto, datas, numeros, esperado", [
    ("em 17/06/2026", ["17/06/2026"], [], True),
    ("em 06/2026", ["17/06/2026"], [], True),
    ("acórdão 3102-004.203", [], ["3102-004.203"], True),
    ("sem dado", ["17/06/2026"], ["3102-004.203"], False),
    ("qualquer data 01/01/2026", [], [], True),
    ("sem nada", [], [], False),
])
def test_cita_dado(texto, datas, numeros, esperado):
    assert cita_dado(texto, datas, numeros) is esperado


def test_validar_recomendacoes_toda_candidata_refutada_com_texto_no_slot():
    cands = [Candidata(**_CAND_OBS)]
    parsed = {"recomendacoes_respondidas": [{"codigo": "pa_irmao_mesma_tese", "resposta": "refutada",
                                             "motivo": "tese diferente"}]}
    ok, erros = validar_recomendacoes(parsed, cands, {"observacao": _OBS_BOA}, ["observacao"])
    assert ok[0].resposta == "refutada"
    assert [e.campo for e in erros] == ["observacao"] and "foi refutada" in erros[0].erro

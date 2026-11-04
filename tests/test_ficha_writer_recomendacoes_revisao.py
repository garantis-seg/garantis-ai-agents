"""A revisão das candidatas de `alerta` e `observacao` no writer.

Regra do dono: nenhum alerta trava a ficha. Os slots `alerta.texto` e
`observacao` são opcionais e nunca reprovam o job. A regra 15 (`cita_dado`) é a
mesma da A61 do shared: os 2 repos rodam os casos de
`tests/fixtures/cita_dado_casos.json`. Sem rede e sem LLM.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from src.agents.ficha_writer.prompts_v4 import _bloco_recomendacoes
from src.agents.ficha_writer.schemas import Candidata
from src.agents.ficha_writer.validacao import (
    RE_ACAO_OBSERVACAO,
    RE_TEXTO_GENERICO,
    cita_dado,
    validar_recomendacoes,
)
from tests.test_ficha_writer_recomendacoes import (
    _ALERTA_BOM,
    _BULLET,
    _CAND_ALERTA,
    _CAND_OBS,
    _OBS_BOA,
    _Prov,
    _body_v5,
    _emissao,
    _leituras,
    _req_v4,
    _roda_v4,
    _rodar_v5,
    _saida,
)

FIXTURES = Path(__file__).parent / "fixtures"
_RE_DATA = re.compile(r"\b\d{2}/\d{2}/\d{4}\b")


# ── H1: a cópia do schema que o shared lê é o schema ─────────────────────────

def _contrato_do_schema() -> dict[str, Any]:
    """O schema de `Candidata` na forma da fixture que o shared lê."""
    js = Candidata.model_json_schema()
    campos: dict[str, Any] = {}
    for nome, p in js["properties"].items():
        if "anyOf" in p:
            s = next(x for x in p["anyOf"] if x.get("type") == "string")
            regra: dict[str, Any] = {"tipo": "string|null"}
            if "maxLength" in s:
                regra["max"] = s["maxLength"]
        elif p.get("type") == "array":
            assert p["items"] == {"type": "string"}, nome
            regra = {"tipo": "lista_string"}
        elif p.get("type") == "integer":
            regra = {"tipo": "int", "gt": p["exclusiveMinimum"]}
        else:
            regra = {"tipo": "string"}
            if "enum" in p:
                regra["enum"] = sorted(p["enum"])
            if "minLength" in p:
                regra["min"] = p["minLength"]
            if "maxLength" in p:
                regra["max"] = p["maxLength"]
            if "pattern" in p:
                regra["padrao"] = p["pattern"]
        campos[nome] = regra
    return {"extra_proibido": js.get("additionalProperties") is False,
            "obrigatorios": sorted(js["required"]), "campos": campos}


def test_a_copia_do_contrato_no_shared_e_o_schema_de_hoje():
    fixture = json.loads((FIXTURES / "contrato_candidata_shared.json").read_text())
    fixture = {k: v for k, v in fixture.items() if not k.startswith("_")}
    assert fixture == _contrato_do_schema()


def test_controle_o_comparador_acha_o_teto_mudado():
    fixture = json.loads((FIXTURES / "contrato_candidata_shared.json").read_text())
    fixture = {k: v for k, v in fixture.items() if not k.startswith("_")}
    fixture["campos"]["fato"]["max"] = 999
    assert fixture != _contrato_do_schema()


# ── M5: cita_dado igual nos 2 repos ──────────────────────────────────────────

_CASOS = json.loads((FIXTURES / "cita_dado_casos.json").read_text())["casos"]


@pytest.mark.parametrize("caso", _CASOS, ids=lambda c: c["texto"][:30])
def test_cita_dado_paridade_com_a_s5(caso):
    assert cita_dado(caso["texto"], caso["datas"], caso["numeros"], pa=caso["pa"]) is caso["esperado"]


def test_o_proprio_pa_nao_cita_o_gatilho(monkeypatch):
    """O PA está no esqueleto: citar só ele reprova (regra 15)."""
    from tests.test_ficha_writer import _PA

    cand = {**_CAND_OBS, "numeros": [_PA]}
    ruim = _saida({"bullets[0]": _BULLET, "alerta.texto": "", "observacao": f"O PA {_PA} segue no CARF."},
                  [{"codigo": "pa_irmao_mesma_tese", "resposta": "redigida"}])
    r, prov = _roda_v4(monkeypatch, _req_v4([cand]), [ruim, ruim, ruim])
    assert "sem a data ou o número do gatilho" in prov.prompts[1]
    # Esgotado só no slot de alerta: o slot sai, e a ficha segue.
    assert r.success is True and "observacao" not in r.campos


# ── H2 (a): esgotado só com erro de alerta, o writer responde success ────────

def test_v4_esgotado_so_com_erro_de_alerta_devolve_success_sem_o_slot(monkeypatch):
    ruim = _saida({"bullets[0]": _BULLET, "alerta.texto": "O mérito foi mantido — a multa cai.",
                   "observacao": _OBS_BOA},
                  [{"codigo": "voto_qualidade_multa", "resposta": "redigida"},
                   {"codigo": "pa_irmao_mesma_tese", "resposta": "redigida"}])
    r, prov = _roda_v4(monkeypatch, _req_v4([_CAND_ALERTA, _CAND_OBS]), [ruim, ruim, ruim])
    assert r.success is True, r.error
    assert len(prov.prompts) == 3
    assert "alerta.texto" not in r.campos
    assert r.campos["bullets[0]"] == _BULLET and r.campos["observacao"] == _OBS_BOA
    assert "recomendacoes_descartadas:alerta.texto" in r.avisos
    assert [x.codigo for x in r.recomendacoes_respondidas] == ["pa_irmao_mesma_tese"]


def test_controle_v4_erro_fora_do_alerta_ainda_reprova(monkeypatch):
    ruim = _saida({"bullets[0]": "x" * 151, "alerta.texto": "O mérito foi mantido — a multa cai.",
                   "observacao": ""}, [{"codigo": "voto_qualidade_multa", "resposta": "redigida"}])
    r, _ = _roda_v4(monkeypatch, _req_v4([_CAND_ALERTA]), [ruim, ruim, ruim])
    assert r.success is False


def test_v5_esgotado_so_com_erro_de_alerta_devolve_success_sem_o_slot(monkeypatch):
    em = _emissao()
    em["campos"]["alerta.texto"] = "O mérito foi mantido — a multa cai."
    em["recomendacoes_respondidas"] = [{"codigo": "voto_qualidade_multa", "resposta": "redigida"}]
    prov = _Prov(_leituras(), [em])
    r = _rodar_v5(prov, monkeypatch, _body_v5([_CAND_ALERTA]))
    assert r.success is True, r.error
    assert "alerta.texto" not in r.campos and r.campos.get("merito.p1")
    assert "recomendacoes_descartadas:alerta.texto" in r.avisos
    assert r.recomendacoes_respondidas == []


# ── H2 (c): o erro da regra 13 volta no slot da candidata ────────────────────

def test_candidata_sem_resposta_reescreve_so_o_slot_dela(monkeypatch):
    sem_resposta = _saida({"bullets[0]": _BULLET, "alerta.texto": _ALERTA_BOM, "observacao": ""}, [])
    bom = _saida({"alerta.texto": _ALERTA_BOM},
                 [{"codigo": "voto_qualidade_multa", "resposta": "redigida"}])
    r, prov = _roda_v4(monkeypatch, _req_v4([_CAND_ALERTA]), [sem_resposta, bom])
    assert r.success is True and r.rodadas == 2
    chaves = prov.prompts[1].split("com EXATAMENTE estas chaves: ")[1].split(".\n")[0]
    assert chaves == '"alerta.texto"'


def test_regra_13_aponta_o_slot_da_candidata():
    cands = [Candidata(**_CAND_ALERTA)]
    _, erros = validar_recomendacoes({}, cands, {}, ["alerta.texto"])
    assert [e.campo for e in erros] == ["alerta.texto"]
    # Sem o slot pedido, o erro fica na lista de respostas.
    _, erros2 = validar_recomendacoes({}, cands, {}, [])
    assert [e.campo for e in erros2] == ["recomendacoes_respondidas"]


# ── LOW 9: a volta do S6 sem slot de alerta não pede a resposta ──────────────

def test_request_sem_slot_de_alerta_nao_exige_resposta_da_candidata(monkeypatch):
    body = _req_v4([_CAND_ALERTA], campos=[{"nome": "bullets[0]", "path": "bullets[0]", "max": 150}])
    r, prov = _roda_v4(monkeypatch, body, [_saida({"bullets[0]": _BULLET}, [])])
    assert r.success is True and r.rodadas == 1
    assert "[voto_qualidade_multa]" not in prov.prompts[0]


# ── LOW: as regex e o texto que vai ao modelo ────────────────────────────────

@pytest.mark.parametrize("texto, pede", [
    ("A peça de defesa de 12/03/2025 trata de outro PA.", False),
    ("As peças de 12/03/2025 tratam de outro PA.", False),
    ("Peça a certidão de 12/03/2025 ao cartório.", True),
    ("Confira o PA 16327.720083/2022-28.", True),
])
def test_acao_nao_confunde_o_substantivo_peca(texto, pede):
    assert bool(RE_ACAO_OBSERVACAO.search(texto)) is pede


def test_texto_generico_no_plural():
    assert RE_TEXTO_GENERICO.search("As empresas ainda dispõem de estratégias jurídicas.")
    assert RE_TEXTO_GENERICO.search("A empresa ainda dispõe de estratégias jurídicas.")


def test_sem_data_no_texto_que_vai_ao_modelo():
    assert not _RE_DATA.search(_bloco_recomendacoes([]))
    cands = [Candidata(**{**_CAND_OBS, "datas": [], "numeros": ["16327.720083/2022-28"]})]
    parsed = {"recomendacoes_respondidas": [{"codigo": "pa_irmao_mesma_tese", "resposta": "redigida"}]}
    casos = [{"observacao": "Confira o PA 16327.720083/2022-28."},
             {"observacao": "Sem número nenhum."},
             {"alerta.texto": "Alerta sem gatilho."},
             {"observacao": "O PA 16327.720083/2022-28 ainda dispõe de estratégias jurídicas."}]
    msgs = [e.erro for c in casos for e in validar_recomendacoes(
        parsed, cands, c, ["observacao", "alerta.texto"])[1]]
    assert len(msgs) >= 4
    assert [m for m in msgs if _RE_DATA.search(m)] == []
    assert not any("1 frase" in m for m in msgs)


def _linhas_datadas(nome: str, texto: str) -> list[str]:
    """As linhas do regime das candidatas com uma data."""
    return [f"{nome}:{n}: {linha.strip()}" for n, linha in enumerate(texto.splitlines(), 1)
            if ("candidat" in linha.lower() or "recomenda" in linha.lower())
            and _RE_DATA.search(linha)]


def test_sem_data_nos_comentarios_do_regime_das_candidatas():
    raiz = Path(__file__).resolve().parent.parent / "src" / "agents" / "ficha_writer"
    achados = [a for arq in ("validacao.py", "prompts_v4.py", "prompts_v5.py", "schemas.py",
                             "agent.py", "agent_v5.py")
               for a in _linhas_datadas(arq, (raiz / arq).read_text())]
    assert achados == []
    # Controle positivo: o scanner acha a data plantada.
    assert _linhas_datadas("x.py", "# As candidatas (03/11/2026).")

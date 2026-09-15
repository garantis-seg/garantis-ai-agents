"""O C5 le o candidato SCAN (fatia 2 da cabeca dos autos, card 869equgwd, OK Elton 15/09).

Pool sem scan = a chamada de texto de hoje, byte a byte. Pool com scan = a de texto sobre os
candidatos de texto + 1 Vision SO dos scans (decisao Elton 15/09: misturadas, o PDF quebrou o
determinismo e contaminou o julgamento do texto). Respostas voltam pra numeracao global.
"""
from __future__ import annotations

import io
import json

import pytest
from pypdf import PdfReader, PdfWriter

from src.agents._utils import ocr_gate, vision
from src.agents.peticao_confirmador import agent as agent_mod
from src.agents.peticao_confirmador.prompts import SISTEMA
from tests.test_peticao_confirmador_rota import (HEAD_1, HEAD_2, ROTA, _mock_provider,
                                                 _req, _veredito, client)  # noqa: F401


def _pdf(paginas: int) -> bytes:
    w = PdfWriter()
    for _ in range(paginas):
        w.add_blank_page(width=100, height=100)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def _vision_fake(monkeypatch, resposta=_veredito(0)):
    """Grava a chamada Vision e serve os PDFs por URL (`gs://b/<paginas>` ou `gs://b/sumido`)."""
    chamadas: list[dict] = []

    async def _fetch(urls):
        return [] if urls[0].endswith("sumido") else [_pdf(int(urls[0].rsplit("/", 1)[1]))]

    async def _call(provider, **kw):
        chamadas.append(kw)
        from types import SimpleNamespace
        return SimpleNamespace(text=resposta, model=kw["model"], input_tokens=900,
                               output_tokens=30, cached_tokens=0,
                               metadata={"cost_usd": 0.0009, "model_variant": "vision"})

    monkeypatch.setattr(agent_mod, "fetch_pdfs_from_gcs", _fetch)
    monkeypatch.setattr(agent_mod, "call_vision_l1", _call)
    return chamadas


def _scan(n, url):
    return {"n": n, "doc_key": f"esc-{n}", "titulo": "Auto", "head": "", "gcs_url": url}


def _pool_misto():
    req = _req()
    t1, t2, _ = req["candidatos"]
    req["candidatos"] = [t1, _scan(2, "gs://b/40"), t2, _scan(4, "gs://b/3")]
    return req


def test_pool_sem_scan_e_a_chamada_de_hoje(client, monkeypatch):
    """⛔ MUTANTE: mandar pro Vision todo candidato com `gcs_url`. `head` presente = texto."""
    vis = _vision_fake(monkeypatch)
    fake = _mock_provider(monkeypatch, _veredito(1))
    req = _req()
    req["candidatos"][0]["gcs_url"] = "gs://b/3"
    body = client.post(ROTA, json=req).json()
    assert fake.n_chamadas == 1 and vis == []
    assert "PDF DO CANDIDATO" not in fake.chamadas[0]["prompt"]
    assert body["usage"]["model_variant"] == "text"


def test_texto_e_scan_vao_em_chamadas_SEPARADAS(client, monkeypatch):
    """⛔ MUTANTE: juntar os PDFs na chamada de texto (o desenho medido e refutado em 15/09)."""
    vis = _vision_fake(monkeypatch)
    fake = _mock_provider(monkeypatch, _veredito(0))
    body = client.post(ROTA, json=_pool_misto()).json()

    assert fake.n_chamadas == 1 and len(vis) == 1
    texto = fake.chamadas[0]["prompt"]
    assert HEAD_1 in texto and HEAD_2 in texto and "PDF DO CANDIDATO" not in texto
    assert "Escolha entre os candidatos [1] a [2]" in texto, "so os 2 de texto"
    kw = vis[0]
    assert HEAD_1 not in kw["prompt"], "o scan nao ve o texto"
    assert "Escolha entre os candidatos [1] a [2]" in kw["prompt"], "so os 2 scans"
    assert kw["rotulos"] == ["PDF DO CANDIDATO [1]", "PDF DO CANDIDATO [2]"]
    assert agent_mod._MARCA_PDF.format(p=2, i=1) in kw["prompt"]
    assert (kw["system_instruction"], kw["temperature"], kw["top_p"], kw["top_k"],
            kw["thinking_budget"], kw["max_tokens"]) == (SISTEMA, 0.0, 1.0, 1, 0, 2048)
    assert kw["seed"] == agent_mod._SEED_SCAN
    assert "seed" not in fake.chamadas[0], "o texto segue sem seed, como foi medido"
    assert [len(PdfReader(io.BytesIO(b)).pages) for b in kw["pdf_bytes_list"]] == [2, 2]
    assert "gs://" not in body["llm_raw_prompt"]
    assert body["card"]["escolhido"] == 0
    assert body["usage"]["cost_usd"] == pytest.approx(0.0001 + 0.0009)
    assert body["usage"]["model_variant"] == "vision"


def test_afirmacao_do_scan_volta_na_numeracao_GLOBAL(client, monkeypatch):
    """⛔ MUTANTE: devolver o indice local. Scan local [2] = global [4]."""
    _vision_fake(monkeypatch, json.dumps({"escolhido": 2, "continuacao": [1, 9],
                                          "motivo": "abre enderecando"}))
    _mock_provider(monkeypatch, _veredito(0))
    card = client.post(ROTA, json=_pool_misto()).json()["card"]
    assert card["escolhido"] == 4
    assert card["continuacao"] == [2, 5], "invalido local vira invalido GLOBAL (n+1)"


def test_afirmacao_do_texto_volta_na_numeracao_GLOBAL(client, monkeypatch):
    _vision_fake(monkeypatch)
    _mock_provider(monkeypatch, _veredito(2))
    assert client.post(ROTA, json=_pool_misto()).json()["card"]["escolhido"] == 3


def test_as_duas_afirmando_e_ABSTENCAO(client, monkeypatch):
    """⛔ MUTANTE: preferir uma das duas. Duas pecas inaugurais = uma delas e errada."""
    _vision_fake(monkeypatch, _veredito(1))
    _mock_provider(monkeypatch, _veredito(1))
    card = client.post(ROTA, json=_pool_misto()).json()["card"]
    assert card["escolhido"] == 0 and card["continuacao"] == []


def test_bool_no_pool_misto_nao_vira_abstencao(client, monkeypatch):
    """⛔ MUTANTE: `escolhido != 0` como filtro — `False == 0` e o scan sumiria como abstencao."""
    _vision_fake(monkeypatch, json.dumps({"escolhido": False, "continuacao": [], "motivo": "x"}))
    _mock_provider(monkeypatch, _veredito(0))
    assert client.post(ROTA, json=_pool_misto()).status_code == 500


def test_card_quebrado_em_qualquer_chamada_e_500(client, monkeypatch):
    _vision_fake(monkeypatch, "isto nao e json")
    _mock_provider(monkeypatch, _veredito(1))
    assert client.post(ROTA, json=_pool_misto()).status_code == 500


def test_nenhum_PDF_disponivel_nao_paga_a_chamada_Vision(client, monkeypatch):
    vis = _vision_fake(monkeypatch)
    fake = _mock_provider(monkeypatch, _veredito(0))
    req = _req()
    req["candidatos"] = [req["candidatos"][0], _scan(2, "gs://b/sumido")]
    client.post(ROTA, json=req)
    assert vis == [] and fake.n_chamadas == 1


def test_o_rotulo_e_a_POSICAO_do_scan_e_so_PDF_que_sobe_ganha_rotulo(client, monkeypatch):
    """⛔ MUTANTE: rotular pela ordem dos anexos. O 1o scan some; o PDF que sobe e o [2]."""
    vis = _vision_fake(monkeypatch)
    _mock_provider(monkeypatch, _veredito(0))
    req = _req(head_paginas=3)
    req["candidatos"] = [_scan(1, "gs://b/sumido"), _scan(2, "gs://b/5")]
    client.post(ROTA, json=req)
    kw = vis[0]
    assert kw["rotulos"] == ["PDF DO CANDIDATO [2]"] and len(kw["pdf_bytes_list"]) == 1
    assert agent_mod._MARCA_SEM_PDF in kw["prompt"]
    assert agent_mod._MARCA_PDF.format(p=3, i=2) in kw["prompt"]


def test_PDF_acima_do_cap_nao_sobe(client, monkeypatch):
    monkeypatch.setattr(agent_mod, "_INLINE_PER_PDF_BYTES_CAP", 10)
    vis = _vision_fake(monkeypatch)
    fake = _mock_provider(monkeypatch, _veredito(0))
    req = _req()
    req["candidatos"] = [req["candidatos"][0], _scan(2, "gs://b/1")]
    client.post(ROTA, json=req)
    assert vis == [] and fake.n_chamadas == 1


def test_inicio_do_pdf_corta_so_o_COMECO():
    assert len(PdfReader(io.BytesIO(ocr_gate.inicio_do_pdf(_pdf(41), 2))).pages) == 2
    curto = _pdf(1)
    assert ocr_gate.inicio_do_pdf(curto, 2) is curto
    assert ocr_gate.inicio_do_pdf(b"<p>html</p>", 2) is None


class _Types:
    class GenerateContentConfig:
        def __init__(self, **kw):
            self.kw = kw

    class ThinkingConfig:
        def __init__(self, **kw):
            pass

    class Part:
        def __init__(self, **kw):
            self.pdf = True

        @staticmethod
        def from_text(text):
            return text

    class Blob:
        def __init__(self, **kw):
            pass


def _prov(visto):
    class _Models:
        async def generate_content(self, model, contents, config):
            visto.append((config.kw, contents))
            from types import SimpleNamespace
            return SimpleNamespace(text="{}", usage_metadata=None)

    class _Prov:
        _types = _Types
        _client = type("C", (), {"aio": type("A", (), {"models": _Models()})()})()

        def get_model_pricing(self, m):
            return {}

    return _Prov()


@pytest.mark.asyncio
async def test_call_vision_l1_encaminha_persona_e_janela_so_quando_pedidas():
    visto = []
    await vision.call_vision_l1(_prov(visto), model="m", prompt="p", pdf_bytes_list=[b"x"],
                                system_instruction="S", top_p=1.0, top_k=1)
    await vision.call_vision_l1(_prov(visto), model="m", prompt="p", pdf_bytes_list=[b"x"])
    com, sem = visto[0][0], visto[1][0]
    assert (com["system_instruction"], com["top_p"], com["top_k"]) == ("S", 1.0, 1)
    assert not {"system_instruction", "top_p", "top_k"} & set(sem)
    assert len(visto[1][1]) == 2, "sem rotulos: PDF + prompt, como sempre"


@pytest.mark.asyncio
async def test_call_vision_l1_intercala_rotulo_ANTES_de_cada_PDF_e_recusa_desalinho():
    visto = []
    await vision.call_vision_l1(_prov(visto), model="m", prompt="p",
                                pdf_bytes_list=[b"a", b"b"], rotulos=["R1", "R2"])
    c = visto[0][1]
    assert (c[0], getattr(c[1], "pdf", False), c[2], getattr(c[3], "pdf", False), c[4]) == \
        ("R1", True, "R2", True, "p")
    with pytest.raises(ValueError):
        await vision.call_vision_l1(_prov([]), model="m", prompt="p",
                                    pdf_bytes_list=[b"a"], rotulos=["R1", "R2"])

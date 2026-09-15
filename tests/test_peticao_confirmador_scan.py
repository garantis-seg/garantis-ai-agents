"""O C5 le o candidato SCAN (fatia 2 da cabeca dos autos, card 869equgwd, OK Elton 15/09).

Candidato com `head` vazio + `gcs_url` vira PDF inline (N primeiras paginas) na MESMA
chamada comparativa; os demais seguem texto. Pool sem scan = chamada de hoje, byte a byte.
"""
from __future__ import annotations

import io

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


@pytest.fixture()
def vision_fake(monkeypatch):
    """Grava a chamada Vision e serve os PDFs por URL (`gs://b/<paginas>` ou `gs://b/sumido`)."""
    chamadas: list[dict] = []

    async def _fetch(urls):
        return [] if urls[0].endswith("sumido") else [_pdf(int(urls[0].rsplit("/", 1)[1]))]

    async def _call(provider, **kw):
        chamadas.append(kw)
        from types import SimpleNamespace
        return SimpleNamespace(text=_veredito(2), model=kw["model"], input_tokens=900,
                               output_tokens=30, cached_tokens=0,
                               metadata={"cost_usd": 0.0009, "model_variant": "vision"})

    monkeypatch.setattr(agent_mod, "fetch_pdfs_from_gcs", _fetch)
    monkeypatch.setattr(agent_mod, "call_vision_l1", _call)
    return chamadas


def _scan(n, url):
    return {"n": n, "doc_key": f"esc-{n}", "titulo": "Auto", "head": "", "gcs_url": url}


def test_pool_sem_scan_segue_a_chamada_de_texto_de_hoje(client, monkeypatch, vision_fake):
    """⛔ MUTANTE: mandar pro Vision todo candidato com `gcs_url`. `head` presente = texto."""
    fake = _mock_provider(monkeypatch, _veredito(1))
    req = _req()
    req["candidatos"][0]["gcs_url"] = "gs://b/3"
    assert client.post(ROTA, json=req).status_code == 200
    assert fake.n_chamadas == 1 and vision_fake == []
    assert HEAD_1 in fake.chamadas[0]["prompt"] and "PDF DO CANDIDATO" not in fake.chamadas[0]["prompt"]


def test_scan_vai_como_PDF_na_MESMA_chamada_com_os_parametros_medidos(client, monkeypatch,
                                                                     vision_fake):
    fake = _mock_provider(monkeypatch, _veredito(1))
    req = _req()
    req["candidatos"] = [req["candidatos"][0], _scan(2, "gs://b/40"), req["candidatos"][1]]
    body = client.post(ROTA, json=req).json()

    assert fake.n_chamadas == 0 and len(vision_fake) == 1, "UMA chamada, e ela e a Vision"
    kw = vision_fake[0]
    assert kw["system_instruction"] == SISTEMA
    assert (kw["temperature"], kw["top_p"], kw["top_k"], kw["thinking_budget"]) == (0.0, 1.0, 1, 0)
    assert kw["max_tokens"] == 2048
    assert [len(PdfReader(io.BytesIO(b)).pages) for b in kw["pdf_bytes_list"]] == [2], \
        "a janela e em PAGINAS: 40 -> 2"
    prompt = kw["prompt"]
    assert HEAD_1 in prompt and HEAD_2 in prompt, "os candidatos de texto seguem texto"
    assert agent_mod._MARCA_PDF.format(p=2, i=2) in prompt
    assert "gs://" not in prompt, "a URL e identidade, nao vai pro prompt"
    assert body["card"]["escolhido"] == 2
    assert body["usage"]["model_variant"] == "vision"


def test_o_rotulo_do_PDF_e_a_POSICAO_do_candidato_e_nao_a_ordem_do_anexo(client, monkeypatch,
                                                                         vision_fake):
    """⛔ MUTANTE: rotular pela ordem dos anexos. No gold scan de 15/09 o modelo casou
    "candidato 3" com "o 3o PDF" e afirmou o documento errado. Aqui o 1o scan some e o 2o
    PDF a subir e o do CANDIDATO [3] — nunca "[1]"."""
    _mock_provider(monkeypatch, _veredito(0))
    req = _req(head_paginas=3)
    req["candidatos"] = [req["candidatos"][0], _scan(2, "gs://b/sumido"), _scan(3, "gs://b/5")]
    client.post(ROTA, json=req)
    kw = vision_fake[0]
    assert kw["rotulos"] == ["PDF DO CANDIDATO [3]"]
    assert len(kw["pdf_bytes_list"]) == 1
    assert agent_mod._MARCA_SEM_PDF in kw["prompt"]
    assert agent_mod._MARCA_PDF.format(p=3, i=3) in kw["prompt"]


def test_PDF_acima_do_cap_nao_ganha_rotulo(client, monkeypatch, vision_fake):
    monkeypatch.setattr(agent_mod, "_INLINE_PER_PDF_BYTES_CAP", 10)
    fake = _mock_provider(monkeypatch, _veredito(0))
    req = _req()
    req["candidatos"] = [req["candidatos"][0], _scan(2, "gs://b/1")]
    client.post(ROTA, json=req)
    assert vision_fake == [] and fake.n_chamadas == 1, "nada coube: volta ao texto"
    assert agent_mod._MARCA_SEM_PDF in fake.chamadas[0]["prompt"]


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

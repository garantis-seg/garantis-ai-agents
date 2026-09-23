"""Labels de cobranca do Vertex no ai-agents (card 869f65eyv) — SDK REAL, transporte
simulado.

Assere o JSON que SAI pro `generateContent`, nao o dict que o provider monta: quem
serializa `labels` no corpo (e quem o RECUSA no AI Studio) e o SDK. Os 3 call sites
que chamam o Gemini: `GeminiProvider` (generate/agenerate, via `_build_config_params`),
`vision.call_vision_l1` e `pdf_ocr.convert_pdf_to_markdown` — os dois ultimos montam o
config A MAO, entao cada um tem teste proprio.

⛔ A `rota` e assertada no corpo capturado DENTRO da request, nunca lendo o ContextVar
de fora do TestClient (fora, ele e None nos dois lados e o teste passa cego).
"""
from __future__ import annotations

import json

import google.auth
import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from google.genai import types
from google.oauth2.credentials import Credentials

from garantis_shared.gemini_backend import make_genai_client
from src.api.middleware import GeminiCallTimeoutMiddleware
from src.providers import LLMFactory
from src.providers.gemini import GeminiProvider, gemini_rota_cv

_MODELO = "gemini-3.1-flash-lite"
_PDF = b"%PDF-1.4 falso"
_RESPOSTA = {
    "candidates": [{
        "content": {"role": "model", "parts": [{"text": "ok"}]},
        "finishReason": "STOP",
    }],
    "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1, "totalTokenCount": 2},
}
_PRODUTOR = {"produtor": "garantis-ai-agents"}


class _Captura:
    """Handler do httpx.MockTransport: grava cada request e responde 200."""

    def __init__(self):
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200, json=_RESPOSTA)

    def corpo(self, i: int = 0) -> dict:
        return json.loads(self.requests[i].content)


def _provider(monkeypatch, backend: str) -> tuple[GeminiProvider, _Captura]:
    for k in ("GEMINI_BACKEND", "GEMINI_API_KEY", "GOOGLE_API_KEY", "GEMINI_VERTEX_PROJECT",
              "GEMINI_VERTEX_LOCATION", "GARANTIS_SERVICE_NAME", "K_SERVICE",
              "CLOUD_RUN_JOB", "CLOUD_RUN_WORKER_POOL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("GEMINI_BACKEND", backend)
    monkeypatch.setenv("K_SERVICE", "garantis-ai-agents")
    if backend == "aistudio":
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    else:  # ADC falsa: o SDK real pede token no 1o request do vertex
        monkeypatch.setattr(
            google.auth, "default", lambda **_kw: (Credentials(token="fake"), "neqsti"),
        )
    cap = _Captura()
    prov = GeminiProvider()
    # O client da factory tem transport de REDE; troca pelo do MESMO construtor da casa
    # com transporte simulado (sync e async — o SDK usa um cliente httpx pra cada).
    prov._client = make_genai_client(prov.api_key, http_options=types.HttpOptions(
        client_args={"transport": httpx.MockTransport(cap)},
        async_client_args={"transport": httpx.MockTransport(cap)},
    ))
    return prov, cap


def _app(prov: GeminiProvider) -> FastAPI:
    app = FastAPI()
    app.add_middleware(GeminiCallTimeoutMiddleware)

    @app.post("/mov-factsheet/classify")
    async def _classify():
        await prov.agenerate("oi", model=_MODELO)
        return {}

    @app.post("/providers/{provider_name}/test")
    async def _testa(provider_name: str):
        await prov.agenerate("oi", model=_MODELO)
        return {}

    return app


def test_rota_do_middleware_chega_no_corpo_do_vertex(monkeypatch):
    prov, cap = _provider(monkeypatch, "vertex")

    with TestClient(_app(prov)) as c:
        assert c.post("/mov-factsheet/classify").status_code == 200
        assert c.post("/providers/gemini/test").status_code == 200

    assert "aiplatform.googleapis.com" in cap.requests[0].url.host  # foi MESMO pro Vertex
    assert [cap.corpo(i)["labels"] for i in range(2)] == [
        {**_PRODUTOR, "rota": "mov-factsheet_classify"},
        # TEMPLATE, nunca o path cru: `providers_gemini_test` seria 1 label por id.
        {**_PRODUTOR, "rota": "providers_provider_name_test"},
    ]


async def test_fora_de_request_sai_so_o_produtor(monkeypatch):
    prov, cap = _provider(monkeypatch, "vertex")

    await prov.agenerate("oi", model=_MODELO)

    assert cap.corpo()["labels"] == _PRODUTOR


def test_generate_sincrono_tambem_leva_labels(monkeypatch):
    prov, cap = _provider(monkeypatch, "vertex")

    prov.generate("oi", model=_MODELO)

    assert cap.corpo()["labels"] == _PRODUTOR


async def test_vision_l1_leva_labels(monkeypatch):
    from src.agents._utils.vision import call_vision_l1

    prov, cap = _provider(monkeypatch, "vertex")
    tok = gemini_rota_cv.set("mov-factsheet_classify")  # o que o middleware poria
    try:
        await call_vision_l1(prov, model=_MODELO, prompt="leia", pdf_bytes_list=[_PDF])
    finally:
        gemini_rota_cv.reset(tok)

    corpo = cap.corpo()
    assert "application/pdf" in json.dumps(corpo["contents"])  # controle: e a multimodal
    assert corpo["labels"] == {**_PRODUTOR, "rota": "mov-factsheet_classify"}


async def test_pdf_ocr_leva_labels(monkeypatch):
    from src.agents.pdf_ocr.agent import convert_pdf_to_markdown

    prov, cap = _provider(monkeypatch, "vertex")
    monkeypatch.setitem(LLMFactory._instances, "gemini", prov)

    r = await convert_pdf_to_markdown(_PDF, provider_name="gemini")

    assert r.success, r.error
    assert cap.corpo()["labels"] == _PRODUTOR


async def test_aistudio_nao_leva_labels_em_nenhum_call_site(monkeypatch):
    """O SDK LEVANTA ValueError com `labels` no AI Studio — label vazado ali nao fica
    so feio: derruba a chamada. Por isso os 4 caminhos rodam aqui."""
    from src.agents._utils.vision import call_vision_l1
    from src.agents.pdf_ocr.agent import convert_pdf_to_markdown

    prov, cap = _provider(monkeypatch, "aistudio")
    monkeypatch.setitem(LLMFactory._instances, "gemini", prov)
    tok = gemini_rota_cv.set("mov-factsheet_classify")
    try:
        await prov.agenerate("oi", model=_MODELO)
        prov.generate("oi", model=_MODELO)
        await call_vision_l1(prov, model=_MODELO, prompt="leia", pdf_bytes_list=[_PDF])
        r = await convert_pdf_to_markdown(_PDF, provider_name="gemini")
        assert r.success, r.error  # o pdf_ocr engole a excecao; o sinal e o success
    finally:
        gemini_rota_cv.reset(tok)

    assert len(cap.requests) == 4
    assert all("generativelanguage" in r.url.host for r in cap.requests)
    assert all("labels" not in json.loads(r.content) for r in cap.requests)

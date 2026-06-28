"""TIER 2 do L2-hang (2026-06-28): o middleware ASGI le o header
X-Gemini-Timeout-Ms (engine read-timeout - buffer) e poe no ContextVar que
agenerate usa pra capar a chamada do Gemini. Testa o parse no trust-boundary
(header externo -> float em segundos) + set/reset por-request.
"""
from __future__ import annotations

import asyncio

from src.api.middleware import GeminiCallTimeoutMiddleware
from src.providers.gemini import gemini_call_timeout_cv


def _run(headers):
    """Roda o middleware com um downstream que captura o CV visto pelo endpoint.
    Retorna (cv_durante_request, cv_depois_request)."""
    seen = {}

    async def app(scope, receive, send):
        seen["during"] = gemini_call_timeout_cv.get()

    async def go():
        mw = GeminiCallTimeoutMiddleware(app)
        await mw({"type": "http", "headers": headers}, None, None)
        return seen.get("during"), gemini_call_timeout_cv.get()

    return asyncio.run(go())


def test_header_vira_segundos_no_cv():
    during, after = _run([(b"x-gemini-timeout-ms", b"40000")])
    assert during == 40.0       # 40000ms -> 40s visivel pro endpoint/agenerate
    assert after is None        # reset apos a request (sem vazar pra proxima)


def test_header_ausente_deixa_cv_none():
    during, after = _run([(b"content-type", b"application/json")])
    assert during is None       # agenerate cai no backstop
    assert after is None


def test_header_invalido_ignorado():
    during, _ = _run([(b"x-gemini-timeout-ms", b"nan")])
    assert during is None


def test_header_nao_positivo_ignorado():
    during, _ = _run([(b"x-gemini-timeout-ms", b"0")])
    assert during is None

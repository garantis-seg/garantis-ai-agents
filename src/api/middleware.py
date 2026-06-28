"""ASGI middleware do garantis-ai-agents."""
from __future__ import annotations

from ..providers.gemini import gemini_call_timeout_cv


class GeminiCallTimeoutMiddleware:
    """Pure-ASGI: le o header X-Gemini-Timeout-Ms (engine read-timeout - buffer) e
    poe no ContextVar que GeminiProvider.agenerate usa pra capar a chamada do Gemini
    (TIER 2 do L2-hang). Pure-ASGI (nao BaseHTTPMiddleware) roda no MESMO task do
    endpoint -> o ContextVar propaga pro agenerate e pros sub-tasks do gather/chunk.
    Header ausente/invalido/<=0 -> nao seta -> agenerate cai no backstop."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        token = None
        if scope["type"] == "http":
            for k, v in scope.get("headers", []):
                if k == b"x-gemini-timeout-ms":
                    try:
                        ms = int(v)
                    except ValueError:
                        break
                    if ms > 0:
                        token = gemini_call_timeout_cv.set(ms / 1000.0)
                    break
        try:
            await self.app(scope, receive, send)
        finally:
            if token is not None:
                gemini_call_timeout_cv.reset(token)

"""ASGI middleware do garantis-ai-agents."""
from __future__ import annotations

from ..providers.gemini import gemini_call_timeout_cv, gemini_service_tier_cv

# Piloto Flex PayGo (2026-09-23): SO o L1 classify — o maior volume do
# gemini-3.1-flash-lite (~16k tokens/call), chamado pela cascade de FUNDO do engine.
# O caminho de imagem (vision.call_vision_l1) chama o client direto e fica no
# Standard. Tirar o path daqui = voltar pro Standard.
# ⛔ Nao ponha rota que alguem espera na tela: Flex tem latencia maior.
_FLEX_PATHS = frozenset({"/mov-factsheet/classify"})


class GeminiCallTimeoutMiddleware:
    """Pure-ASGI: le o header X-Gemini-Timeout-Ms (engine read-timeout - buffer) e
    poe no ContextVar que GeminiProvider.agenerate usa pra capar a chamada do Gemini
    (TIER 2 do L2-hang). Pure-ASGI (nao BaseHTTPMiddleware) roda no MESMO task do
    endpoint -> o ContextVar propaga pro agenerate e pros sub-tasks do gather/chunk.
    Header ausente/invalido/<=0 -> nao seta -> agenerate cai no backstop.
    Marca tambem o tier Flex das rotas em `_FLEX_PATHS` (mesmo mecanismo)."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        token = tier_token = None
        if scope["type"] == "http":
            if scope.get("path") in _FLEX_PATHS:
                tier_token = gemini_service_tier_cv.set("flex")
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
            if tier_token is not None:
                gemini_service_tier_cv.reset(tier_token)

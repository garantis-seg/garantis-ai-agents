"""ASGI middleware do garantis-ai-agents."""
from __future__ import annotations

from typing import Optional

from starlette.routing import Match

from ..providers.gemini import gemini_call_timeout_cv, gemini_rota_cv, label_vertex


def _rota_template(scope) -> Optional[str]:
    """Label `rota` da request: o TEMPLATE da rota (`/providers/{provider_name}/test`),
    nunca o path cru — mesmas 2 razoes do `current_route` do fe-api: segredo no path
    e cardinalidade (path concreto = 1 valor por id, e o GROUP BY da fatura deixa de
    agregar). `scope["route"]` so existe DEPOIS do router, e este middleware roda
    ANTES — por isso a resolucao e explicita, com a MESMA API do router.
    Sem match (404) = None: sem label, nunca o cru."""
    for rota in getattr(scope.get("app"), "routes", ()):
        if rota.matches(scope)[0] is Match.FULL:
            return label_vertex(getattr(rota, "path", "") or "") or None
    return None


class GeminiCallTimeoutMiddleware:
    """Pure-ASGI: le o header X-Gemini-Timeout-Ms (engine read-timeout - buffer) e
    poe no ContextVar que GeminiProvider.agenerate usa pra capar a chamada do Gemini
    (TIER 2 do L2-hang). Pure-ASGI (nao BaseHTTPMiddleware) roda no MESMO task do
    endpoint -> o ContextVar propaga pro agenerate e pros sub-tasks do gather/chunk.
    Header ausente/invalido/<=0 -> nao seta -> agenerate cai no backstop.
    Marca tambem a `rota` que vira label de cobranca no Vertex (mesmo mecanismo)."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        token = rota_token = None
        if scope["type"] == "http":
            rota_token = gemini_rota_cv.set(_rota_template(scope))
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
            if rota_token is not None:
                gemini_rota_cv.reset(rota_token)

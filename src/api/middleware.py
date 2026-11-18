"""ASGI middleware do garantis-ai-agents."""
from __future__ import annotations

import json
import zlib
from typing import Optional

from starlette.routing import Match

from ..providers.gemini import gemini_call_timeout_cv, gemini_rota_cv, label_vertex


def _rota_template(scope) -> Optional[str]:
    """Label `rota` da request: o TEMPLATE da rota (`/x/{id}`),
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


#: O teto do corpo depois de descomprimir. Protege a instância de um corpo malicioso.
TETO_CORPO_DESCOMPRIMIDO = 512 * 1024 * 1024


class CorpoGzipMiddleware:
    """Pure-ASGI: descomprime o corpo do pedido que chega com `Content-Encoding: gzip`.

    O Cloud Run recusa o pedido HTTP/1 acima de 32 MiB com HTTP 413, antes de o app ver
    o pedido. O dossiê de um conexo grande passa disso (loop de fichas, 17/11/2026,
    conexo 1481152: 413 no qualificador e no redator, em 2 rodadas). O cliente do
    `garantis-shared` comprime o corpo grande, e este middleware devolve o JSON cru às
    rotas. Sem o cabeçalho, o pedido passa sem toque.
    """

    def __init__(self, app, teto: int = TETO_CORPO_DESCOMPRIMIDO) -> None:
        self.app = app
        self.teto = teto

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or not any(
                k == b"content-encoding" and v.strip().lower() == b"gzip"
                for k, v in scope.get("headers", [])):
            await self.app(scope, receive, send)
            return
        pedacos: list[bytes] = []
        while True:
            msg = await receive()
            if msg["type"] != "http.request":
                # O cliente desligou antes do fim do corpo.
                return
            pedacos.append(msg.get("body", b""))
            if not msg.get("more_body"):
                break
        try:
            corpo = self._descomprimir(b"".join(pedacos))
        except (OSError, EOFError, zlib.error, ValueError) as e:
            await self._erro(send, 400 if not isinstance(e, ValueError) else 413, str(e)[:200])
            return
        scope = dict(scope)
        scope["headers"] = [(k, v) for k, v in scope["headers"]
                            if k not in (b"content-encoding", b"content-length")]
        scope["headers"].append((b"content-length", str(len(corpo)).encode()))
        entregue = False

        async def receber():
            nonlocal entregue
            if not entregue:
                entregue = True
                return {"type": "http.request", "body": corpo, "more_body": False}
            return await receive()

        await self.app(scope, receber, send)

    def _descomprimir(self, bruto: bytes) -> bytes:
        d = zlib.decompressobj(16 + zlib.MAX_WBITS)
        corpo = d.decompress(bruto, self.teto + 1)
        if len(corpo) > self.teto:
            raise ValueError(f"corpo descomprimido acima de {self.teto} bytes")
        if not d.eof:
            raise EOFError("corpo gzip incompleto")
        return corpo

    @staticmethod
    async def _erro(send, status: int, detalhe: str) -> None:
        corpo = json.dumps({"detail": f"corpo gzip inválido: {detalhe}"}).encode()
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json"),
                                (b"content-length", str(len(corpo)).encode())]})
        await send({"type": "http.response.body", "body": corpo})

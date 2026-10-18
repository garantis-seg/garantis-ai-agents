"""
Factory para criação de clientes de modelos.
"""

import socket

import httpx
from google import genai
from google.genai import types

# TCP keepalive pro hop ai-agents->Google, espelhando o
# garantis_shared.http_clients._AI_AGENTS_SOCKET_OPTIONS (que cobre o hop
# anterior engine->ai-agents). Sem isto o genai SDK usa o transport httpx default
# (zero keepalive tuning): uma conexao half-open guardada no pool (Google LB
# reciclou, sem RST) e REUSADA -> a request vai pro vazio -> pendura ate o teto.
# Com SO_KEEPALIVE o OS sonda conexoes idle e DERRUBA as mortas -> o reuse vira
# ConnectError rapido (transport retries=2 reabsorve) em vez de ReadTimeout no
# vazio. Linux-only opts via getattr (Cloud Run = Linux; no-op no dev box).
# ⚠️ Higiene geral do hop, NAO cura de stall: conexao fresca e baixa concorrencia
# reproduziram o stall do L2 do mesmo jeito — a causa era o modelo (gemini-2.5-flash
# pendurando em certos prompts), resolvida trocando o modelo, nao o transporte.
_GENAI_SOCKET_OPTIONS: list = [(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)]
for _opt_name, _opt_val in (("TCP_KEEPIDLE", 10), ("TCP_KEEPINTVL", 5), ("TCP_KEEPCNT", 3)):
    _opt = getattr(socket, _opt_name, None)
    if _opt is not None:
        _GENAI_SOCKET_OPTIONS.append((socket.IPPROTO_TCP, _opt, _opt_val))

# ⛔ O `limits` MORA NO TRANSPORT (abaixo), nunca ao lado dele: quando o client
# recebe `transport=`, o httpx IGNORA o `limits` passado junto, em silencio, e o
# pool roda no DEFAULT (100 / keepalive 20 / expiry 5s).
# O que o 40/15s compra e so menos handshake TLS com o Gemini; ⚠️ NAO e cura de
# conexao morta (expiry MAIOR alarga a janela de reuso). `tests/test_genai_pool_limits.py`
# le o pool EFETIVO.
_GENAI_LIMITS = httpx.Limits(
    max_connections=100, max_keepalive_connections=40, keepalive_expiry=15.0,
)

# HttpOptions.timeout (MILISSEGUNDOS) e a UNICA forma de dar timeout ao httpx do
# genai: timeout dentro de *_client_args e sobrescrito por-request pra None
# (=desabilitado) pelo SDK. 600s = backstop (>= o maior layer legitimo, L3); o
# asyncio.wait_for do GeminiProvider.agenerate e o guard real e mais
# apertado por-camada via header X-Gemini-Timeout-Ms, entao dispara antes.
_GENAI_TIMEOUT_MS = 600_000


def create_genai_client() -> genai.Client:
    """
    Cria um cliente genai com TCP keepalive no transport httpx (sync + async).

    Returns:
        Cliente genai configurado. SINGLETON por processo — o caller (GeminiProvider
        do `create_provider`) NAO deve recriar por-request: rebuildar o cliente
        recria o pool e anula o keepalive.
    """
    # O backend, o endpoint e a auth sao do `make_genai_client` do shared (inclusive a
    # chave e o erro sem chave, no modo aistudio). Aqui so entra o http_options
    # (transport/keepalive/limits), que vale nos dois modos.
    from garantis_shared.gemini_backend import make_genai_client

    # NOTA: sync e async exigem instancias de transport SEPARADAS (httpx.HTTPTransport
    # vs httpx.AsyncHTTPTransport — classes diferentes, nao da pra compartilhar).
    return make_genai_client(
        http_options=types.HttpOptions(
            timeout=_GENAI_TIMEOUT_MS,
            client_args={
                "transport": httpx.HTTPTransport(
                    retries=2, socket_options=_GENAI_SOCKET_OPTIONS,
                    limits=_GENAI_LIMITS,
                ),
            },
            async_client_args={
                "transport": httpx.AsyncHTTPTransport(
                    retries=2, socket_options=_GENAI_SOCKET_OPTIONS,
                    limits=_GENAI_LIMITS,
                ),
            },
        ),
    )

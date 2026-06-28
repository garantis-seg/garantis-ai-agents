"""
Factory para criação de clientes de modelos.
"""

import os
import socket
from typing import Optional

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
# 2026-06-28 UPDATE: keepalive NAO era a causa do stall de L2. Provado por teste:
# conexao fresca (keepalive=0) E baixa concorrencia (sem=2) deram o MESMO ~79% stall;
# e o stall reproduz em ISOLAMENTO num proc especifico. A causa REAL era o
# gemini-2.5-flash PENDURANDO deterministico em certos prompts (fix = trocar o modelo
# pro 3.1, ver agents/*/agent.py). Este keepalive fica como higiene geral do hop
# (nao prejudica), nao como fix do stall.
_GENAI_SOCKET_OPTIONS: list = [(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)]
for _opt_name, _opt_val in (("TCP_KEEPIDLE", 10), ("TCP_KEEPINTVL", 5), ("TCP_KEEPCNT", 3)):
    _opt = getattr(socket, _opt_name, None)
    if _opt is not None:
        _GENAI_SOCKET_OPTIONS.append((socket.IPPROTO_TCP, _opt, _opt_val))

_GENAI_LIMITS = httpx.Limits(
    max_connections=100, max_keepalive_connections=40, keepalive_expiry=15.0,
)

# HttpOptions.timeout (MILISSEGUNDOS) e a UNICA forma de dar timeout ao httpx do
# genai: timeout dentro de *_client_args e sobrescrito por-request pra None
# (=desabilitado) pelo SDK. 600s = backstop (>= o maior layer legitimo, L3); o
# asyncio.wait_for do GeminiProvider.agenerate (TIER 2) e o guard real e mais
# apertado por-camada via header X-Gemini-Timeout-Ms, entao dispara antes.
_GENAI_TIMEOUT_MS = 600_000


def create_genai_client(api_key: Optional[str] = None) -> genai.Client:
    """
    Cria um cliente genai com TCP keepalive no transport httpx (sync + async).

    Args:
        api_key: API key do Gemini. Se None, usa GEMINI_API_KEY do ambiente.

    Returns:
        Cliente genai configurado. SINGLETON por processo — o caller (GeminiProvider
        via LLMFactory cache) NAO deve recriar por-request: rebuildar o cliente
        recria o pool e anula o keepalive.

    Raises:
        ValueError: Se não houver API key disponível.
    """
    api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable not set")

    # NOTA: sync e async exigem instancias de transport SEPARADAS (httpx.HTTPTransport
    # vs httpx.AsyncHTTPTransport — classes diferentes, nao da pra compartilhar).
    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            timeout=_GENAI_TIMEOUT_MS,
            client_args={
                "transport": httpx.HTTPTransport(
                    retries=2, socket_options=_GENAI_SOCKET_OPTIONS,
                ),
                "limits": _GENAI_LIMITS,
            },
            async_client_args={
                "transport": httpx.AsyncHTTPTransport(
                    retries=2, socket_options=_GENAI_SOCKET_OPTIONS,
                ),
                "limits": _GENAI_LIMITS,
            },
        ),
    )

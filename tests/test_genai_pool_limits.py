"""O `limits` do pool ai-agents->Gemini tem de valer no pool EFETIVO, sync e async.

Com `transport=` explicito o httpx IGNORA o `limits` passado ao lado dele, em
silencio. Ate 2026-09-23 o `_GENAI_LIMITS` ia no `client_args` e os dois pools
rodavam no default (100 / keepalive 20 / expiry 5s) — o mesmo defeito do
garantis-shared#576. Le o pool de verdade, nao a config.
"""
from __future__ import annotations

import os

os.environ.setdefault("GEMINI_API_KEY", "dummy-test-key")
os.environ.setdefault("GEMINI_BACKEND", "aistudio")

from src.models.factory import create_genai_client  # noqa: E402


def test_limits_valem_nos_pools_sync_e_async():
    api = create_genai_client("dummy-test-key")._api_client
    for nome in ("_httpx_client", "_async_httpx_client"):
        pool = getattr(api, nome)._transport._pool
        assert (pool._max_connections, pool._max_keepalive_connections, pool._keepalive_expiry) == (
            100, 40, 15.0), f"{nome}: o limits nao chegou no pool — ele tem de ir DENTRO do transport"

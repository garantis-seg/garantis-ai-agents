"""TPM limiter do provider Gemini (2026-06-21) — conta TOKENS, não requests.

Fecha o gap do limiter de RPS, que deixava bulk-cascade de prompts grandes
estourar o tokens/min do Gemini → degradação → JSON truncado (l1_degraded).
Causa-raiz provada em memory l1-truncation-load-induced-2026-06-21.
"""
import asyncio
import time

from src.providers.gemini import _TokenRateLimiter


def test_acquire_within_bucket_is_fast():
    async def run():
        lim = _TokenRateLimiter(rate=1000, bucket_size=1000, name="t")
        t0 = time.monotonic()
        await lim.acquire(800, timeout=1)        # bucket tem 1000 → sem espera
        assert time.monotonic() - t0 < 0.3
    asyncio.run(run())


def test_throttles_when_drained():
    async def run():
        lim = _TokenRateLimiter(rate=1000, bucket_size=1000, name="t")  # 1000 tok/s
        await lim.acquire(1000, timeout=1)       # drena o bucket
        t0 = time.monotonic()
        await lim.acquire(500, timeout=2)        # precisa ~0.5s de refill
        assert time.monotonic() - t0 >= 0.4      # ESPEROU o refill = throttle real
    asyncio.run(run())


def test_timeout_when_starved():
    async def run():
        lim = _TokenRateLimiter(rate=1, bucket_size=10, name="t")  # 1 tok/s, lento
        await lim.acquire(10, timeout=1)         # drena
        try:
            await lim.acquire(10, timeout=0.3)   # precisa ~10s, timeout 0.3 → raise
            assert False, "deveria estourar TimeoutError"
        except asyncio.TimeoutError:
            pass
    asyncio.run(run())


def test_cost_capped_to_bucket_no_deadlock():
    async def run():
        lim = _TokenRateLimiter(rate=10000, bucket_size=100, name="t")
        # cost 5000 > bucket 100 → capado p/ 100, adquire sem deadlock
        await asyncio.wait_for(lim.acquire(5000, timeout=1), timeout=2)
    asyncio.run(run())


def test_reconcile_debits_output_overflow():
    async def run():
        lim = _TokenRateLimiter(rate=1, bucket_size=1000, name="t")  # refill lento
        await lim.acquire(100, timeout=1)            # ~900 restantes
        lim.reconcile(estimated=100, actual=900)     # output real estourou → debita 800
        try:
            await lim.acquire(300, timeout=0.3)      # só ~100 left + refill lento → raise
            assert False, "reconcile não debitou o excedente do output"
        except asyncio.TimeoutError:
            pass
    asyncio.run(run())

"""
Gemini LLM Provider - Google Gemini API implementation.

Provides access to Google's Gemini models with support for
structured output via response_schema.
"""

import asyncio
import contextvars
import os
import logging
import time
from typing import Any, Dict, List, Optional, Type

from garantis_shared.rate_limit import TokenBucketRateLimiter

from .base import BaseLLMProvider, LLMResponse

logger = logging.getLogger(__name__)

# Rate limiter global per-process — protege contra 503 storms quando varios
# agentes (mov_factsheet/processo_synthesis/merito_synthesis/etc)
# disparam Gemini em paralelo. Single chokepoint: todos os agentes que usam
# GeminiProvider compartilham este limiter.
#
# Sizing (Tier 3 paid):
#   - flash-lite global: 30k RPM = 500 RPS
#   - ai-agents max_instances=100 (worst case scaling)
#   - per-process: 500 / 100 = 5 RPS sustained
#   - burst 10: cobre L1 gather (mov + day) com Semaphore(5)
#
# Override via env GEMINI_RATE_LIMIT_RPS / GEMINI_RATE_LIMIT_BURST se preciso
# ajustar sem redeploy (e.g. degrade rapido em incident).
_GEMINI_RATE = float(os.getenv("GEMINI_RATE_LIMIT_RPS", "5.0"))
_GEMINI_BURST = int(os.getenv("GEMINI_RATE_LIMIT_BURST", "10"))
_GEMINI_ACQUIRE_TIMEOUT_S = float(os.getenv("GEMINI_RATE_LIMIT_TIMEOUT_S", "60.0"))

# ── Per-call timeout do generate_content (TIER 2 do L2-hang, 2026-06-28) ──────
# O generate_content NAO tinha timeout proprio: quando o Gemini stalla, a call
# pendurava ate o teto de-facto do SDK (~230-250s observado nos logs) enquanto o
# engine ja desistiu aos 45s (read-timeout) e gravou timeout 0-token -> slot de
# worker + chamada Gemini PAGA desperdicados num orfao. O engine manda o header
# X-Gemini-Timeout-Ms (= seu read-timeout - buffer); o middleware ASGI poe no CV
# abaixo; agenerate capa a call nesse teto via asyncio.wait_for -> falha rapido
# (retryable no caller) e a cancelacao aborta a conexao orfa. Header ausente
# (testes/outros callers) -> backstop generoso que nao corta L3 legitimo.
gemini_call_timeout_cv: "contextvars.ContextVar[Optional[float]]" = (
    contextvars.ContextVar("gemini_call_timeout_s", default=None)
)
_GEMINI_CALL_TIMEOUT_BACKSTOP_S = float(os.getenv("GEMINI_CALL_TIMEOUT_S", "600.0"))

_gemini_rate_limiter = TokenBucketRateLimiter(
    rate=_GEMINI_RATE,
    bucket_size=_GEMINI_BURST,
    name="gemini",
)

# ── TPM limiter (2026-06-21) ──────────────────────────────────────────────────
# O RPS acima só conta REQUESTS; bulk-cascade de prompts grandes passa no RPS mas
# estoura o tokens/min do Gemini → trunca (l1_degraded; causa-raiz provada, memory
# l1-truncation-load-induced). Este conta TOKENS. Default 3M tok/min/process: um
# cascade limpo MEDIU pico ~1.42M TPM (não throttla 1-2 cascades); concorrência alta
# (loop ~6× = >8M) throttla pra ficar sob o teto do Gemini. Tune via env.
_GEMINI_TPM = float(os.getenv("GEMINI_RATE_LIMIT_TPM", "3000000"))


class _TokenRateLimiter:
    """Token bucket onde 1 token = 1 token de API (não 1 request) — cost-aware.
    ponytail: espelha garantis_shared.TokenBucketRateLimiter mas com acquire(cost)
    + reconcile pós-call; consolidar lá se ganhar um 2o caller."""

    def __init__(self, rate: float, bucket_size: float, name: str):
        self.rate = rate
        self.bucket_size = float(bucket_size)
        self.name = name
        self._tokens = float(bucket_size)
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        self._tokens = min(self.bucket_size, self._tokens + (now - self._last) * self.rate)
        self._last = now

    async def acquire(self, cost: float, timeout: float) -> None:
        cost = min(float(cost), self.bucket_size)  # anti-deadlock: nunca pede > bucket
        start = time.monotonic()
        while True:
            async with self._lock:
                self._refill()
                if self._tokens >= cost:
                    self._tokens -= cost
                    return
                wait_needed = (cost - self._tokens) / self.rate
            elapsed = time.monotonic() - start
            if elapsed >= timeout:
                logger.warning(
                    "RateLimiter '%s' TPM timeout %.1fs (cost=%.0f)",
                    self.name, elapsed, cost,
                )
                raise asyncio.TimeoutError(f"{self.name} TPM timeout {elapsed:.1f}s")
            await asyncio.sleep(min(wait_needed, timeout - elapsed, 0.25))

    def reconcile(self, estimated: float, actual: float) -> None:
        # pós-call: debita o que o estimado não cobriu (output real >> reserva).
        # Sem lock/espera — best-effort; pode deixar _tokens negativo → throttla a
        # próxima. ponytail: micro-race no float tolerável p/ rate limit.
        extra = actual - estimated
        if extra > 0:
            self._tokens = max(self._tokens - extra, -self.bucket_size)


_gemini_tpm_limiter = _TokenRateLimiter(
    rate=_GEMINI_TPM / 60.0,
    bucket_size=_GEMINI_TPM,  # ~1 min de burst
    name="gemini-tpm",
)

# Model pricing (USD per 1M tokens) - Updated Dec 2024
GEMINI_PRICING = {
    "gemini-2.5-pro": {"input_per_1m": 1.25, "output_per_1m": 10.00},
    "gemini-2.5-flash": {"input_per_1m": 0.15, "output_per_1m": 0.60},
    "gemini-2.5-flash-lite": {"input_per_1m": 0.075, "output_per_1m": 0.30},
    "gemini-2.0-flash": {"input_per_1m": 0.10, "output_per_1m": 0.40},
    "gemini-2.0-flash-lite": {"input_per_1m": 0.075, "output_per_1m": 0.30},
    "gemini-1.5-pro": {"input_per_1m": 1.25, "output_per_1m": 5.00},
    "gemini-1.5-flash": {"input_per_1m": 0.075, "output_per_1m": 0.30},
}

DEFAULT_MODEL = "gemini-2.5-flash-lite"


# Terminações NORMAIS do Gemini. STOP = ok; MAX_TOKENS = corte legítimo de tamanho
# (caller trata/chunka). QUALQUER outra (SAFETY / RECITATION / PROHIBITED_CONTENT /
# OTHER / MALFORMED_FUNCTION_CALL...) deixa `response.text` PARCIAL → o parse
# downstream falha com 'Unterminated string'. O provider Gemini IGNORAVA o
# finish_reason (≠ providers OpenAI/OpenRouter, que já o expõem) — então a causa
# real ficava invisível e o L1 só via 'JSONDecodeError char N'.
_GEMINI_NORMAL_FINISH = {"STOP", "FINISH_REASON_STOP", "MAX_TOKENS"}


def _gemini_finish_reason(response: Any) -> Optional[str]:
    """finish_reason do 1º candidate como str (enum.name) ou None — defensivo."""
    try:
        cand = (getattr(response, "candidates", None) or [None])[0]
        fr = getattr(cand, "finish_reason", None)
        return getattr(fr, "name", None) or (str(fr) if fr is not None else None)
    except Exception:
        return None


def _gemini_text_and_finish(response: Any, model: str) -> tuple[str, Optional[str]]:
    """Extrai (text, finish_reason) e LOGA terminação anormal (prefix grepável
    GEMINI_ABNORMAL_FINISH, p/ alert policy). text='' se response.text levantar
    (resposta bloqueada / sem candidate). NÃO muda comportamento — só dá visibilidade
    da causa quando o card vem truncado."""
    finish_reason = _gemini_finish_reason(response)
    try:
        text = response.text
    except Exception as e:
        text = ""
        logger.warning(
            "GEMINI_RESPONSE_TEXT_RAISED model=%s finish_reason=%s err=%r",
            model, finish_reason, e,
        )
    if finish_reason and finish_reason not in _GEMINI_NORMAL_FINISH:
        try:
            cand = (getattr(response, "candidates", None) or [None])[0]
            safety = getattr(cand, "safety_ratings", None) if cand else None
        except Exception:
            safety = None
        logger.warning(
            "GEMINI_ABNORMAL_FINISH model=%s finish_reason=%s text_len=%d "
            "prompt_feedback=%r safety=%r — response.text vem PARCIAL (parse vai falhar)",
            model, finish_reason, len(text or ""),
            getattr(response, "prompt_feedback", None), safety,
        )
    return text, finish_reason


class GeminiProvider(BaseLLMProvider):
    """
    Google Gemini LLM provider.

    Uses the google-genai SDK for accessing Gemini models.
    Supports structured output via response_schema parameter.
    """

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize Gemini provider.

        Args:
            api_key: Gemini API key. If None, reads from GEMINI_API_KEY env var.
        """
        super().__init__()

        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            raise ValueError("No GEMINI_API_KEY provided or found in environment")

        # Import here to avoid issues if not installed
        try:
            import google.genai as genai
            from google.genai import types

            self._genai = genai
            self._types = types
        except ImportError:
            raise ImportError(
                "google-genai package not installed. Install with: pip install google-genai"
            )

        # Initialize client via factory — transport httpx com TCP keepalive (sync+
        # async) pro hop ai-agents->Google nao pendurar em conexao half-open stale
        # sob burst (hedge do stall L2; ver models/factory.py).
        from ..models.factory import create_genai_client

        self._client = create_genai_client(self.api_key)
        self._default_model = DEFAULT_MODEL

        logger.info(f"GeminiProvider initialized with default model: {self._default_model}")

    def _build_config_params(
        self,
        *,
        temperature: float,
        max_tokens: int,
        response_schema: Optional[Type],
        model: str,
        **kwargs,
    ) -> Dict[str, Any]:
        """Build kwargs p/ GenerateContentConfig — centralizado p/ generate/agenerate.

        Determinismo: quando temperature=0, force top_p=1.0 + top_k=1 (greedy
        strict decoding). Gemini 2.5 tem thinking mode ON by default — caller
        passa thinking_budget=0 p/ disable (elimina variabilidade dos thinking
        tokens, ver Bug 4 handoff).
        """
        config_params: Dict[str, Any] = {
            "temperature": temperature,
            "max_output_tokens": max_tokens,
        }

        # Structured output
        if response_schema is not None:
            config_params["response_mime_type"] = "application/json"
            config_params["response_schema"] = response_schema
        elif kwargs.get("response_mime_type"):
            # Permite forcar JSON output sem passar response_schema
            # (necessario quando schema tem dict[str, Any] que Gemini Developer API rejeita)
            config_params["response_mime_type"] = kwargs["response_mime_type"]

        # Greedy strict decoding quando temperature=0 (top_p=1, top_k=1).
        # Override possivel via kwargs.
        if temperature == 0.0:
            config_params["top_p"] = kwargs.get("top_p", 1.0)
            config_params["top_k"] = kwargs.get("top_k", 1)
        else:
            if "top_p" in kwargs:
                config_params["top_p"] = kwargs["top_p"]
            if "top_k" in kwargs:
                config_params["top_k"] = kwargs["top_k"]

        # Thinking mode (Gemini 2.5 only). thinking_budget=0 desabilita.
        # Caller opt-in: nao mexer se kwarg ausente, preserva default SDK.
        thinking_budget = kwargs.get("thinking_budget")
        if thinking_budget is not None and "2.5" in (model or ""):
            try:
                config_params["thinking_config"] = self._types.ThinkingConfig(
                    thinking_budget=thinking_budget,
                )
            except (AttributeError, TypeError) as e:
                logger.warning(
                    "ThinkingConfig not supported by SDK; ignoring thinking_budget=%s: %r",
                    thinking_budget, e,
                )

        # Seed (opcional — fixa seed do sampler quando SDK suporta).
        seed = kwargs.get("seed")
        if seed is not None:
            try:
                # SDK pode aceitar direto em GenerateContentConfig OR rejeitar.
                config_params["seed"] = seed
            except Exception:
                pass

        return config_params

    def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 16384,
        response_schema: Optional[Type] = None,
        **kwargs,
    ) -> LLMResponse:
        """
        Generate content using Gemini.

        Args:
            prompt: The text prompt.
            model: Model to use (defaults to gemini-2.5-flash-lite).
            temperature: Sampling temperature.
            max_tokens: Maximum output tokens.
            response_schema: Pydantic model for structured JSON output.
            **kwargs: Additional parameters.

        Returns:
            LLMResponse with generated content.
        """
        model = model or self._default_model
        config_params = self._build_config_params(
            temperature=temperature,
            max_tokens=max_tokens,
            response_schema=response_schema,
            model=model,
            **kwargs,
        )
        config = self._types.GenerateContentConfig(**config_params)

        # Make API call
        response = self._client.models.generate_content(
            model=model,
            contents=prompt,
            config=config,
        )

        # Extract token counts
        input_tokens = 0
        output_tokens = 0
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            input_tokens = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
            output_tokens = getattr(response.usage_metadata, "candidates_token_count", 0) or 0

        text, finish_reason = _gemini_text_and_finish(response, model)
        return LLMResponse(
            text=text,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            raw_response=response,
            metadata={
                "provider": "gemini",
                "finish_reason": finish_reason,
                "cost_usd": self.calculate_cost(model, input_tokens, output_tokens),
            },
        )

    async def agenerate(
        self,
        prompt: str,
        model: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 16384,
        response_schema: Optional[Type] = None,
        **kwargs,
    ) -> LLMResponse:
        """
        Async generate content using Gemini.

        Args:
            prompt: The text prompt.
            model: Model to use.
            temperature: Sampling temperature.
            max_tokens: Maximum output tokens.
            response_schema: Pydantic model for structured JSON output.
            **kwargs: Additional parameters. Reconhecidos p/ determinismo:
                - thinking_budget (int, 0 = thinking OFF em gemini-2.5-*)
                - top_p (float, default 1.0 quando temperature=0)
                - top_k (int, default 1 quando temperature=0)
                - seed (int, fixa seed do sampler se SDK suporta)

        Returns:
            LLMResponse with generated content.
        """
        model = model or self._default_model
        config_params = self._build_config_params(
            temperature=temperature,
            max_tokens=max_tokens,
            response_schema=response_schema,
            model=model,
            **kwargs,
        )
        config = self._types.GenerateContentConfig(**config_params)

        # Rate limit ANTES da call — single chokepoint protege contra 503 storms.
        # asyncio.TimeoutError propagada e tratada como retryable pelo caller
        # (frontend-api ai_agents.call ja trata httpx.HTTPError + TimeoutError).
        await _gemini_rate_limiter.acquire(timeout=_GEMINI_ACQUIRE_TIMEOUT_S)
        # TPM: input (≈4 chars/token, conhecido) + reserva output. reconcile() abaixo
        # corrige com o uso REAL pós-call (output gigante debita o excedente).
        _est_tokens = (len(prompt) if isinstance(prompt, str) else 4096) // 4 + 2048
        await _gemini_tpm_limiter.acquire(_est_tokens, timeout=_GEMINI_ACQUIRE_TIMEOUT_S)

        # Make async API call — BOUNDED (TIER 2): sem isto o generate_content pendura
        # ate o teto do SDK (~230-250s) quando o Gemini stalla. O CV vem do header
        # X-Gemini-Timeout-Ms (engine read-timeout - buffer); ausente -> backstop.
        # wait_for cancela a coroutine no estouro -> aborta a chamada orfa.
        _call_timeout_s = gemini_call_timeout_cv.get() or _GEMINI_CALL_TIMEOUT_BACKSTOP_S
        try:
            response = await asyncio.wait_for(
                self._client.aio.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=config,
                ),
                timeout=_call_timeout_s,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "GEMINI_CALL_TIMEOUT model=%s timeout=%.0fs prompt_chars=%d — "
                "abortado (retryable no caller)",
                model, _call_timeout_s,
                len(prompt) if isinstance(prompt, str) else -1,
            )
            raise

        # Extract token counts
        input_tokens = 0
        output_tokens = 0
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            input_tokens = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
            output_tokens = getattr(response.usage_metadata, "candidates_token_count", 0) or 0

        # Reconcilia o TPM com o uso real (estimativa cobriu input+reserva; output
        # real pode estourar a reserva — debita a diferença, throttla a próxima).
        _gemini_tpm_limiter.reconcile(_est_tokens, (input_tokens or 0) + (output_tokens or 0))

        text, finish_reason = _gemini_text_and_finish(response, model)
        return LLMResponse(
            text=text,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            raw_response=response,
            metadata={
                "provider": "gemini",
                "finish_reason": finish_reason,
                "cost_usd": self.calculate_cost(model, input_tokens, output_tokens),
            },
        )

    def test_connection(self) -> bool:
        """Test Gemini API connection."""
        try:
            response = self.generate(
                prompt="Responda apenas 'OK'.",
                model=self._default_model,
                max_tokens=10,
            )
            return bool(response.text and "OK" in response.text.upper())
        except Exception as e:
            logger.error(f"Gemini connection test failed: {e}")
            return False

    def get_available_models(self) -> List[str]:
        """Get list of available Gemini models."""
        return list(GEMINI_PRICING.keys())

    def get_default_model(self) -> str:
        """Get default model."""
        return self._default_model

    def get_model_pricing(self, model: str) -> Dict[str, float]:
        """Get pricing for a Gemini model."""
        return GEMINI_PRICING.get(model, {"input_per_1m": 0.0, "output_per_1m": 0.0})

    def supports_structured_output(self) -> bool:
        """Gemini supports structured output via response_schema."""
        return True

    def set_default_model(self, model: str) -> None:
        """
        Set the default model.

        Args:
            model: Model name to use as default.
        """
        if model in GEMINI_PRICING:
            self._default_model = model
            logger.info(f"Default Gemini model set to: {model}")
        else:
            logger.warning(f"Unknown model {model}, keeping current default: {self._default_model}")

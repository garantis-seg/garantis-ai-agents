"""
Gemini LLM Provider - Google Gemini API implementation.

Provides access to Google's Gemini models with support for
structured output via response_schema.
"""

import os
import logging
from typing import Any, Dict, List, Optional, Type

from garantis_shared.rate_limit import TokenBucketRateLimiter

from .base import BaseLLMProvider, LLMResponse

logger = logging.getLogger(__name__)

# Rate limiter global per-process — protege contra 503 storms quando varios
# agentes (mov_factsheet/day_factsheet/processo_synthesis/merito_synthesis/etc)
# disparam Gemini em paralelo. Single chokepoint: todos os agentes que usam
# GeminiProvider compartilham este limiter.
#
# Sizing (Tier 3 paid):
#   - flash-lite global: 30k RPM = 500 RPS
#   - ai-agents max_instances=100 (worst case scaling)
#   - per-process: 500 / 100 = 5 RPS sustained
#   - burst 10: cobre L1 3-way gather (mov + day + monolith) com Semaphore(5)
#
# Override via env GEMINI_RATE_LIMIT_RPS / GEMINI_RATE_LIMIT_BURST se preciso
# ajustar sem redeploy (e.g. degrade rapido em incident).
_GEMINI_RATE = float(os.getenv("GEMINI_RATE_LIMIT_RPS", "5.0"))
_GEMINI_BURST = int(os.getenv("GEMINI_RATE_LIMIT_BURST", "10"))
_GEMINI_ACQUIRE_TIMEOUT_S = float(os.getenv("GEMINI_RATE_LIMIT_TIMEOUT_S", "60.0"))

_gemini_rate_limiter = TokenBucketRateLimiter(
    rate=_GEMINI_RATE,
    bucket_size=_GEMINI_BURST,
    name="gemini",
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

        # Initialize client
        self._client = genai.Client(api_key=self.api_key)
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

        return LLMResponse(
            text=response.text,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            raw_response=response,
            metadata={
                "provider": "gemini",
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

        # Make async API call
        response = await self._client.aio.models.generate_content(
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

        return LLMResponse(
            text=response.text,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            raw_response=response,
            metadata={
                "provider": "gemini",
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

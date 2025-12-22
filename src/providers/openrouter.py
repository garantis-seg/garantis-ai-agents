"""
OpenRouter LLM Provider - OpenRouter API implementation.

Provides access to multiple AI models through OpenRouter's unified API,
including free tiers of various providers (DeepSeek, Llama, etc.).
"""

import os
import json
import logging
from typing import Any, Dict, List, Optional, Type

from .base import BaseLLMProvider, LLMResponse

logger = logging.getLogger(__name__)

# Model pricing (USD per 1M tokens) - OpenRouter pricing Dec 2024
# Note: Some models have free tiers with rate limits
OPENROUTER_PRICING = {
    # Free models (rate limited)
    "deepseek/deepseek-chat-v3.1:free": {"input_per_1m": 0.0, "output_per_1m": 0.0},
    "meta-llama/llama-3.1-8b-instruct:free": {"input_per_1m": 0.0, "output_per_1m": 0.0},
    "google/gemma-2-9b-it:free": {"input_per_1m": 0.0, "output_per_1m": 0.0},
    # Paid models
    "deepseek/deepseek-chat-v3.1": {"input_per_1m": 0.14, "output_per_1m": 0.28},
    "anthropic/claude-3.5-sonnet": {"input_per_1m": 3.00, "output_per_1m": 15.00},
    "anthropic/claude-3-haiku": {"input_per_1m": 0.25, "output_per_1m": 1.25},
    "openai/gpt-4o": {"input_per_1m": 2.50, "output_per_1m": 10.00},
    "openai/gpt-4o-mini": {"input_per_1m": 0.15, "output_per_1m": 0.60},
    "meta-llama/llama-3.1-70b-instruct": {"input_per_1m": 0.52, "output_per_1m": 0.75},
    "google/gemini-pro": {"input_per_1m": 0.125, "output_per_1m": 0.375},
}

# Default model - DeepSeek free tier for cost efficiency
DEFAULT_MODEL = "deepseek/deepseek-chat-v3.1:free"


class OpenRouterProvider(BaseLLMProvider):
    """
    OpenRouter LLM provider for multi-model access.

    Uses OpenRouter's unified API which is OpenAI-compatible
    and provides access to multiple providers including free tiers.
    """

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize OpenRouter provider.

        Args:
            api_key: OpenRouter API key. If None, reads from OPENROUTER_API_KEY env var.
        """
        super().__init__()

        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        if not self.api_key:
            raise ValueError("No OPENROUTER_API_KEY provided or found in environment")

        # Optional site info for OpenRouter rankings
        self.site_url = os.getenv("OPENROUTER_SITE_URL", "")
        self.site_name = os.getenv("OPENROUTER_SITE_NAME", "GARANTIS_AI_AGENTS")

        # Import here to avoid issues if not installed
        try:
            from openai import OpenAI, AsyncOpenAI

            self._OpenAI = OpenAI
            self._AsyncOpenAI = AsyncOpenAI
        except ImportError:
            raise ImportError(
                "openai package not installed. Install with: pip install openai"
            )

        # Initialize clients with OpenRouter base URL
        self._client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=self.api_key,
        )
        self._async_client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=self.api_key,
        )
        self._default_model = DEFAULT_MODEL

        logger.info(f"OpenRouterProvider initialized with default model: {self._default_model}")

    def _get_extra_headers(self) -> Dict[str, str]:
        """Get extra headers for OpenRouter API requests."""
        headers = {}
        if self.site_url:
            headers["HTTP-Referer"] = self.site_url
        if self.site_name:
            headers["X-Title"] = self.site_name
        return headers

    def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 4096,
        response_schema: Optional[Type] = None,
        **kwargs,
    ) -> LLMResponse:
        """
        Generate content using OpenRouter.

        Args:
            prompt: The text prompt.
            model: Model to use (defaults to deepseek free tier).
            temperature: Sampling temperature.
            max_tokens: Maximum output tokens.
            response_schema: Pydantic model for structured JSON output.
            **kwargs: Additional parameters (e.g., system_message).

        Returns:
            LLMResponse with generated content.
        """
        model = model or self._default_model

        # Build messages
        messages = []

        system_message = kwargs.get("system_message")
        if system_message:
            messages.append({"role": "system", "content": system_message})

        # Add JSON schema instruction if response_schema provided
        user_content = prompt
        if response_schema:
            schema_json = json.dumps(response_schema.model_json_schema(), indent=2)
            user_content = (
                f"{prompt}\n\nRespond with valid JSON only, matching this schema:\n{schema_json}"
            )

        messages.append({"role": "user", "content": user_content})

        # Build request params
        request_params = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "extra_headers": self._get_extra_headers(),
        }

        # Make API call
        response = self._client.chat.completions.create(**request_params)

        # Extract response
        choice = response.choices[0]
        text = choice.message.content or ""

        return LLMResponse(
            text=text,
            model=model,
            input_tokens=response.usage.prompt_tokens if response.usage else 0,
            output_tokens=response.usage.completion_tokens if response.usage else 0,
            total_tokens=response.usage.total_tokens if response.usage else 0,
            raw_response=response,
            metadata={
                "provider": "openrouter",
                "finish_reason": choice.finish_reason,
                "cost_usd": self.calculate_cost(
                    model,
                    response.usage.prompt_tokens if response.usage else 0,
                    response.usage.completion_tokens if response.usage else 0,
                ),
            },
        )

    async def agenerate(
        self,
        prompt: str,
        model: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 4096,
        response_schema: Optional[Type] = None,
        **kwargs,
    ) -> LLMResponse:
        """
        Async generate content using OpenRouter.

        Args:
            prompt: The text prompt.
            model: Model to use.
            temperature: Sampling temperature.
            max_tokens: Maximum output tokens.
            response_schema: Pydantic model for structured JSON output.
            **kwargs: Additional parameters.

        Returns:
            LLMResponse with generated content.
        """
        model = model or self._default_model

        # Build messages
        messages = []
        system_message = kwargs.get("system_message")
        if system_message:
            messages.append({"role": "system", "content": system_message})

        user_content = prompt
        if response_schema:
            schema_json = json.dumps(response_schema.model_json_schema(), indent=2)
            user_content = (
                f"{prompt}\n\nRespond with valid JSON only, matching this schema:\n{schema_json}"
            )

        messages.append({"role": "user", "content": user_content})

        request_params = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "extra_headers": self._get_extra_headers(),
        }

        # Make async API call
        response = await self._async_client.chat.completions.create(**request_params)

        choice = response.choices[0]
        text = choice.message.content or ""

        return LLMResponse(
            text=text,
            model=model,
            input_tokens=response.usage.prompt_tokens if response.usage else 0,
            output_tokens=response.usage.completion_tokens if response.usage else 0,
            total_tokens=response.usage.total_tokens if response.usage else 0,
            raw_response=response,
            metadata={
                "provider": "openrouter",
                "finish_reason": choice.finish_reason,
                "cost_usd": self.calculate_cost(
                    model,
                    response.usage.prompt_tokens if response.usage else 0,
                    response.usage.completion_tokens if response.usage else 0,
                ),
            },
        )

    def test_connection(self) -> bool:
        """Test OpenRouter API connection."""
        try:
            response = self.generate(
                prompt="Responda apenas 'OK'.",
                model=self._default_model,
                max_tokens=10,
            )
            return bool(response.text and "OK" in response.text.upper())
        except Exception as e:
            logger.error(f"OpenRouter connection test failed: {e}")
            return False

    def get_available_models(self) -> List[str]:
        """Get list of available OpenRouter models."""
        try:
            # Try to fetch from API
            models = self._client.models.list()
            return [m.id for m in models.data if m.id]
        except Exception:
            # Fallback to known models
            return list(OPENROUTER_PRICING.keys())

    def get_default_model(self) -> str:
        """Get default model."""
        return self._default_model

    def get_model_pricing(self, model: str) -> Dict[str, float]:
        """Get pricing for an OpenRouter model."""
        return OPENROUTER_PRICING.get(model, {"input_per_1m": 0.0, "output_per_1m": 0.0})

    def supports_structured_output(self) -> bool:
        """OpenRouter supports JSON output via prompt engineering."""
        return True

    def set_default_model(self, model: str) -> None:
        """
        Set the default model.

        Args:
            model: Model name to use as default.
        """
        self._default_model = model
        logger.info(f"Default OpenRouter model set to: {model}")

    def get_rate_limits(self) -> Dict[str, Any]:
        """
        Get rate limit information for OpenRouter.

        Returns:
            Dict with rate limit details.
        """
        return {
            "requests_per_minute": 200,  # Free tier
            "tokens_per_minute": 50000,  # Free tier
            "requests_per_day": 25000,  # Free tier
            "note": "Rates are generous but vary by model. Free models have lower limits.",
        }

    def get_free_models(self) -> List[str]:
        """
        Get list of free models available on OpenRouter.

        Returns:
            List of free model names.
        """
        return [model for model in OPENROUTER_PRICING if ":free" in model]

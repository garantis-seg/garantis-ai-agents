"""
Groq LLM Provider - Groq API implementation for fast inference.

Provides access to Groq's high-speed inference platform with
Llama and other models via OpenAI-compatible API.
"""

import os
import logging
from typing import Any, Dict, List, Optional, Type
import json

from .base import BaseLLMProvider, LLMResponse

logger = logging.getLogger(__name__)

# Model pricing (USD per 1M tokens) - Groq pricing Dec 2024
GROQ_PRICING = {
    "llama-3.3-70b-versatile": {"input_per_1m": 0.59, "output_per_1m": 0.79},
    "llama-3.3-70b-specdec": {"input_per_1m": 0.59, "output_per_1m": 0.99},
    "llama-3.1-70b-versatile": {"input_per_1m": 0.59, "output_per_1m": 0.79},
    "llama-3.1-8b-instant": {"input_per_1m": 0.05, "output_per_1m": 0.08},
    "llama-guard-3-8b": {"input_per_1m": 0.20, "output_per_1m": 0.20},
    "mixtral-8x7b-32768": {"input_per_1m": 0.24, "output_per_1m": 0.24},
    "gemma2-9b-it": {"input_per_1m": 0.20, "output_per_1m": 0.20},
}

# Default model - fast and capable
DEFAULT_MODEL = "llama-3.3-70b-versatile"


class GroqProvider(BaseLLMProvider):
    """
    Groq LLM provider for high-speed inference.

    Uses Groq's API which is OpenAI-compatible but optimized
    for speed with specialized inference hardware.
    """

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize Groq provider.

        Args:
            api_key: Groq API key. If None, reads from GROQ_API_KEY env var.
        """
        super().__init__()

        # Support both GROQ_API_KEY and GROK_API_KEY (common typo)
        self.api_key = api_key or os.getenv("GROQ_API_KEY") or os.getenv("GROK_API_KEY")
        if not self.api_key:
            raise ValueError("No GROQ_API_KEY provided or found in environment")

        # Import here to avoid issues if not installed
        try:
            from groq import Groq, AsyncGroq

            self._Groq = Groq
            self._AsyncGroq = AsyncGroq
        except ImportError:
            raise ImportError(
                "groq package not installed. Install with: pip install groq"
            )

        # Initialize clients
        self._client = Groq(api_key=self.api_key)
        self._async_client = AsyncGroq(api_key=self.api_key)
        self._default_model = DEFAULT_MODEL

        logger.info(f"GroqProvider initialized with default model: {self._default_model}")

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
        Generate content using Groq.

        Args:
            prompt: The text prompt.
            model: Model to use (defaults to llama-3.3-70b-versatile).
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
        }

        # Add JSON mode if schema provided
        if response_schema:
            request_params["response_format"] = {"type": "json_object"}

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
                "provider": "groq",
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
        Async generate content using Groq.

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
        }

        if response_schema:
            request_params["response_format"] = {"type": "json_object"}

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
                "provider": "groq",
                "finish_reason": choice.finish_reason,
                "cost_usd": self.calculate_cost(
                    model,
                    response.usage.prompt_tokens if response.usage else 0,
                    response.usage.completion_tokens if response.usage else 0,
                ),
            },
        )

    def test_connection(self) -> bool:
        """Test Groq API connection."""
        try:
            response = self.generate(
                prompt="Responda apenas 'OK'.",
                model=self._default_model,
                max_tokens=10,
            )
            return bool(response.text and "OK" in response.text.upper())
        except Exception as e:
            logger.error(f"Groq connection test failed: {e}")
            return False

    def get_available_models(self) -> List[str]:
        """Get list of available Groq models."""
        try:
            # Try to fetch from API
            models = self._client.models.list()
            return [m.id for m in models.data if m.id]
        except Exception:
            # Fallback to known models
            return list(GROQ_PRICING.keys())

    def get_default_model(self) -> str:
        """Get default model."""
        return self._default_model

    def get_model_pricing(self, model: str) -> Dict[str, float]:
        """Get pricing for a Groq model."""
        return GROQ_PRICING.get(model, {"input_per_1m": 0.0, "output_per_1m": 0.0})

    def supports_structured_output(self) -> bool:
        """Groq supports JSON mode for structured output."""
        return True

    def set_default_model(self, model: str) -> None:
        """
        Set the default model.

        Args:
            model: Model name to use as default.
        """
        self._default_model = model
        logger.info(f"Default Groq model set to: {model}")

    def get_rate_limits(self) -> Dict[str, Any]:
        """
        Get rate limit information for Groq.

        Returns:
            Dict with rate limit details.
        """
        return {
            "requests_per_minute": 30,  # Free tier
            "tokens_per_minute": 6000,  # Free tier
            "requests_per_day": 14400,  # Free tier
            "note": "Rates vary by subscription tier and model",
        }

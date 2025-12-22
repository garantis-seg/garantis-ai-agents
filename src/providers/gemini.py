"""
Gemini LLM Provider - Google Gemini API implementation.

Provides access to Google's Gemini models with support for
structured output via response_schema.
"""

import os
import logging
from typing import Any, Dict, List, Optional, Type

from .base import BaseLLMProvider, LLMResponse

logger = logging.getLogger(__name__)

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

# Default model
DEFAULT_MODEL = "gemini-2.0-flash"


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
            api_key: Google API key. If None, reads from GOOGLE_API_KEY env var.
        """
        super().__init__()

        self.api_key = api_key or os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            raise ValueError("No GOOGLE_API_KEY provided or found in environment")

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
        Generate content using Gemini.

        Args:
            prompt: The text prompt.
            model: Model to use (defaults to gemini-2.0-flash).
            temperature: Sampling temperature.
            max_tokens: Maximum output tokens.
            response_schema: Pydantic model for structured JSON output.
            **kwargs: Additional parameters.

        Returns:
            LLMResponse with generated content.
        """
        model = model or self._default_model

        # Build generation config
        config_params = {
            "temperature": temperature,
            "max_output_tokens": max_tokens,
        }

        # Add structured output if schema provided
        if response_schema:
            config_params["response_mime_type"] = "application/json"
            config_params["response_schema"] = response_schema

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
        max_tokens: int = 4096,
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
            **kwargs: Additional parameters.

        Returns:
            LLMResponse with generated content.
        """
        model = model or self._default_model

        # Build generation config
        config_params = {
            "temperature": temperature,
            "max_output_tokens": max_tokens,
        }

        if response_schema:
            config_params["response_mime_type"] = "application/json"
            config_params["response_schema"] = response_schema

        config = self._types.GenerateContentConfig(**config_params)

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

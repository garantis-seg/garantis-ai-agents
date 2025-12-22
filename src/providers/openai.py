"""
OpenAI LLM Provider - OpenAI API implementation.

Provides access to OpenAI's GPT models with support for
structured output via response_format.
"""

import os
import json
import logging
from typing import Any, Dict, List, Optional, Type

from .base import BaseLLMProvider, LLMResponse

logger = logging.getLogger(__name__)

# Model pricing (USD per 1M tokens) - Updated Dec 2024
OPENAI_PRICING = {
    "gpt-4o": {"input_per_1m": 2.50, "output_per_1m": 10.00},
    "gpt-4o-mini": {"input_per_1m": 0.15, "output_per_1m": 0.60},
    "gpt-4-turbo": {"input_per_1m": 10.00, "output_per_1m": 30.00},
    "gpt-4": {"input_per_1m": 30.00, "output_per_1m": 60.00},
    "gpt-3.5-turbo": {"input_per_1m": 0.50, "output_per_1m": 1.50},
    "o1": {"input_per_1m": 15.00, "output_per_1m": 60.00},
    "o1-mini": {"input_per_1m": 3.00, "output_per_1m": 12.00},
}

# Default model
DEFAULT_MODEL = "gpt-4o-mini"


class OpenAIProvider(BaseLLMProvider):
    """
    OpenAI LLM provider.

    Uses the openai SDK for accessing GPT models.
    Supports structured output via response_format parameter.
    """

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize OpenAI provider.

        Args:
            api_key: OpenAI API key. If None, reads from OPENAI_API_KEY env var.
        """
        super().__init__()

        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("No OPENAI_API_KEY provided or found in environment")

        # Import here to avoid issues if not installed
        try:
            from openai import OpenAI, AsyncOpenAI

            self._OpenAI = OpenAI
            self._AsyncOpenAI = AsyncOpenAI
        except ImportError:
            raise ImportError(
                "openai package not installed. Install with: pip install openai"
            )

        # Initialize clients
        self._client = OpenAI(api_key=self.api_key)
        self._async_client = AsyncOpenAI(api_key=self.api_key)
        self._default_model = DEFAULT_MODEL

        logger.info(f"OpenAIProvider initialized with default model: {self._default_model}")

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
        Generate content using OpenAI.

        Args:
            prompt: The text prompt.
            model: Model to use (defaults to gpt-4o-mini).
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

        # Add system message if provided
        system_message = kwargs.get("system_message")
        if system_message:
            messages.append({"role": "system", "content": system_message})

        messages.append({"role": "user", "content": prompt})

        # Build request params
        request_params = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        # Add structured output if schema provided
        if response_schema:
            # OpenAI uses response_format with JSON schema
            request_params["response_format"] = {"type": "json_object"}
            # Add schema instruction to prompt
            schema_json = json.dumps(response_schema.model_json_schema(), indent=2)
            messages[-1]["content"] = (
                f"{prompt}\n\nRespond with valid JSON matching this schema:\n{schema_json}"
            )

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
                "provider": "openai",
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
        Async generate content using OpenAI.

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
        messages.append({"role": "user", "content": prompt})

        # Build request params
        request_params = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if response_schema:
            request_params["response_format"] = {"type": "json_object"}
            schema_json = json.dumps(response_schema.model_json_schema(), indent=2)
            messages[-1]["content"] = (
                f"{prompt}\n\nRespond with valid JSON matching this schema:\n{schema_json}"
            )

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
                "provider": "openai",
                "finish_reason": choice.finish_reason,
                "cost_usd": self.calculate_cost(
                    model,
                    response.usage.prompt_tokens if response.usage else 0,
                    response.usage.completion_tokens if response.usage else 0,
                ),
            },
        )

    def test_connection(self) -> bool:
        """Test OpenAI API connection."""
        try:
            response = self.generate(
                prompt="Responda apenas 'OK'.",
                model=self._default_model,
                max_tokens=10,
            )
            return bool(response.text and "OK" in response.text.upper())
        except Exception as e:
            logger.error(f"OpenAI connection test failed: {e}")
            return False

    def get_available_models(self) -> List[str]:
        """Get list of available OpenAI models."""
        return list(OPENAI_PRICING.keys())

    def get_default_model(self) -> str:
        """Get default model."""
        return self._default_model

    def get_model_pricing(self, model: str) -> Dict[str, float]:
        """Get pricing for an OpenAI model."""
        return OPENAI_PRICING.get(model, {"input_per_1m": 0.0, "output_per_1m": 0.0})

    def supports_structured_output(self) -> bool:
        """OpenAI supports structured output via response_format."""
        return True

    def set_default_model(self, model: str) -> None:
        """
        Set the default model.

        Args:
            model: Model name to use as default.
        """
        if model in OPENAI_PRICING:
            self._default_model = model
            logger.info(f"Default OpenAI model set to: {model}")
        else:
            logger.warning(f"Unknown model {model}, keeping current default: {self._default_model}")

"""
Base LLM Provider - Abstract interface for all LLM providers.

Defines the common interface that all LLM providers must implement,
enabling provider-agnostic usage and easy switching between providers.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Type
import logging

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    """Standardized response from LLM providers."""

    text: str
    """The generated text content."""

    model: str
    """The model used for generation."""

    input_tokens: int = 0
    """Number of input tokens used."""

    output_tokens: int = 0
    """Number of output tokens generated."""

    total_tokens: int = 0
    """Total tokens used (input + output)."""

    raw_response: Optional[Any] = None
    """Raw response from the provider (for debugging)."""

    metadata: Dict[str, Any] = field(default_factory=dict)
    """Additional metadata from the provider."""

    @property
    def cost_usd(self) -> float:
        """Calculate cost in USD based on token usage."""
        # Default implementation - providers can override with actual pricing
        return 0.0


class BaseLLMProvider(ABC):
    """
    Abstract base class for all LLM providers.

    All concrete providers (Gemini, OpenAI, Groq, etc.) must inherit
    from this class and implement the required methods.
    """

    def __init__(self):
        """Initialize base LLM provider."""
        self.provider_name = self.__class__.__name__.replace("Provider", "").lower()
        self._client: Optional[Any] = None

    @property
    def name(self) -> str:
        """Get provider name."""
        return self.provider_name

    @abstractmethod
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
        Generate content using the LLM provider.

        Args:
            prompt: The text prompt to send to the LLM.
            model: Specific model to use (uses provider default if None).
            temperature: Sampling temperature (0.0 to 1.0).
            max_tokens: Maximum tokens to generate.
            response_schema: Optional Pydantic model for structured output.
            **kwargs: Additional provider-specific parameters.

        Returns:
            LLMResponse with generated content and metadata.

        Raises:
            Exception: Provider-specific API errors.
        """
        pass

    @abstractmethod
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
        Async version of generate().

        Args:
            prompt: The text prompt to send to the LLM.
            model: Specific model to use (uses provider default if None).
            temperature: Sampling temperature (0.0 to 1.0).
            max_tokens: Maximum tokens to generate.
            response_schema: Optional Pydantic model for structured output.
            **kwargs: Additional provider-specific parameters.

        Returns:
            LLMResponse with generated content and metadata.
        """
        pass

    @abstractmethod
    def test_connection(self) -> bool:
        """
        Test connection to the LLM provider.

        Returns:
            True if connection is successful, False otherwise.
        """
        pass

    @abstractmethod
    def get_available_models(self) -> List[str]:
        """
        Get list of available models for this provider.

        Returns:
            List of model names/identifiers available for use.
        """
        pass

    def get_default_model(self) -> str:
        """
        Get the default model for this provider.

        Returns:
            Default model name.
        """
        models = self.get_available_models()
        return models[0] if models else "unknown"

    def get_model_pricing(self, model: str) -> Dict[str, float]:
        """
        Get pricing information for a model.

        Args:
            model: Model name.

        Returns:
            Dict with 'input_per_1m' and 'output_per_1m' in USD.
        """
        # Default implementation - providers should override
        return {"input_per_1m": 0.0, "output_per_1m": 0.0}

    def calculate_cost(
        self, model: str, input_tokens: int, output_tokens: int
    ) -> float:
        """
        Calculate cost for token usage.

        Args:
            model: Model used.
            input_tokens: Number of input tokens.
            output_tokens: Number of output tokens.

        Returns:
            Cost in USD.
        """
        pricing = self.get_model_pricing(model)
        input_cost = (input_tokens / 1_000_000) * pricing.get("input_per_1m", 0)
        output_cost = (output_tokens / 1_000_000) * pricing.get("output_per_1m", 0)
        return input_cost + output_cost

    def supports_structured_output(self) -> bool:
        """
        Check if provider supports structured JSON output.

        Returns:
            True if provider supports response_schema parameter.
        """
        return False

    def supports_async(self) -> bool:
        """
        Check if provider supports async operations.

        Returns:
            True if provider has async support.
        """
        return True

    def __str__(self) -> str:
        """String representation."""
        return f"{self.__class__.__name__}(default_model={self.get_default_model()})"

    def __repr__(self) -> str:
        """Detailed representation."""
        return f"{self.__class__.__name__}(provider={self.provider_name})"

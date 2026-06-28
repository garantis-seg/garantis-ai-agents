"""
LLM Factory - Factory pattern for creating LLM provider instances.

Provides a centralized way to create and configure different LLM providers
based on environment configuration or explicit provider selection.
"""

import os
import logging
from typing import Dict, List, Optional, Type

from .base import BaseLLMProvider

logger = logging.getLogger(__name__)


class LLMFactory:
    """
    Factory class for creating LLM provider instances.

    Supports multiple LLM providers (Gemini, OpenAI, Groq, OpenRouter) and allows
    runtime provider selection through environment variables or explicit parameters.
    """

    _registry: Dict[str, Type[BaseLLMProvider]] = {}
    _instances: Dict[str, BaseLLMProvider] = {}  # Cache for singleton instances

    @classmethod
    def register_provider(cls, name: str, provider_class: Type[BaseLLMProvider]) -> None:
        """
        Register a new LLM provider.

        Args:
            name: Provider name (e.g., 'gemini', 'openai', 'groq').
            provider_class: Provider class that inherits from BaseLLMProvider.
        """
        cls._registry[name.lower()] = provider_class
        logger.debug(f"Registered provider: {name}")

    @classmethod
    def create_provider(
        cls,
        provider: Optional[str] = None,
        use_cache: bool = True,
        **kwargs,
    ) -> BaseLLMProvider:
        """
        Create an LLM provider instance.

        Args:
            provider: Provider name. If None, uses DEFAULT_PROVIDER env var.
            use_cache: Whether to cache and reuse instances.
            **kwargs: Additional arguments passed to provider constructor.

        Returns:
            Configured LLM provider instance.

        Raises:
            ValueError: If provider is not supported or not available.
            ImportError: If provider dependencies are not installed.
        """
        # Determine provider
        if provider is None:
            provider = os.getenv("DEFAULT_PROVIDER", "gemini").lower()
        else:
            provider = provider.lower()

        # Check cache first
        if use_cache and provider in cls._instances:
            return cls._instances[provider]

        # Lazy registration of providers
        cls._ensure_providers_registered()

        # Validate provider
        if provider not in cls._registry:
            available = list(cls._registry.keys())
            raise ValueError(f"Unsupported provider: {provider}. Available: {available}")

        # Create instance
        provider_class = cls._registry[provider]
        try:
            instance = provider_class(**kwargs)

            # Cache if requested
            if use_cache:
                cls._instances[provider] = instance

            logger.info(f"Created {provider} provider instance")
            return instance

        except ImportError as e:
            raise ImportError(f"Failed to create {provider} provider. Missing dependencies: {e}")
        except Exception as e:
            raise RuntimeError(f"Failed to initialize {provider} provider: {e}")

    @classmethod
    def get_available_providers(cls) -> List[str]:
        """
        Get list of available LLM providers.

        Returns:
            List of provider names that can be used.
        """
        cls._ensure_providers_registered()
        return list(cls._registry.keys())

    @classmethod
    def test_provider(cls, provider: str) -> bool:
        """
        Test if a provider is working correctly.

        Args:
            provider: Provider name to test.

        Returns:
            True if provider connection test passes, False otherwise.
        """
        try:
            instance = cls.create_provider(provider, use_cache=False)
            return instance.test_connection()
        except Exception as e:
            logger.error(f"Provider test failed for {provider}: {e}")
            return False

    @classmethod
    def get_default_provider(cls) -> str:
        """
        Get the default LLM provider.

        Returns:
            Default provider name from environment or fallback.
        """
        return os.getenv("DEFAULT_PROVIDER", "gemini").lower()

    @classmethod
    def _ensure_providers_registered(cls) -> None:
        """Ensure all available providers are registered."""
        if not cls._registry:
            cls._register_available_providers()

    @classmethod
    def _register_available_providers(cls) -> None:
        """Register all available LLM providers."""
        # Register Gemini provider
        try:
            from .gemini import GeminiProvider

            cls.register_provider("gemini", GeminiProvider)
            logger.debug("Registered Gemini provider")
        except ImportError as e:
            logger.debug(f"Gemini provider not available: {e}")


# Convenience functions for easy usage
def create_provider(provider: Optional[str] = None, **kwargs) -> BaseLLMProvider:
    """Convenience function to create LLM provider."""
    return LLMFactory.create_provider(provider, **kwargs)


def get_available_providers() -> List[str]:
    """Convenience function to get available providers."""
    return LLMFactory.get_available_providers()


def test_provider(provider: str) -> bool:
    """Convenience function to test a provider."""
    return LLMFactory.test_provider(provider)


def get_default_provider() -> str:
    """Convenience function to get default provider."""
    return LLMFactory.get_default_provider()

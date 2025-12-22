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
    def is_provider_available(cls, provider: str) -> bool:
        """
        Check if a specific provider is available.

        Args:
            provider: Provider name to check.

        Returns:
            True if provider is available, False otherwise.
        """
        cls._ensure_providers_registered()
        return provider.lower() in cls._registry

    @classmethod
    def get_provider_info(cls) -> Dict[str, Dict]:
        """
        Get information about all available providers.

        Returns:
            Dict with provider info including models and capabilities.
        """
        cls._ensure_providers_registered()
        provider_info = {}

        for name, provider_class in cls._registry.items():
            try:
                # Try to create instance and get info
                instance = cls.create_provider(name, use_cache=True)
                provider_info[name] = {
                    "default_model": instance.get_default_model(),
                    "available_models": instance.get_available_models(),
                    "supports_structured_output": instance.supports_structured_output(),
                    "supports_async": instance.supports_async(),
                    "class": provider_class.__name__,
                }
            except Exception as e:
                provider_info[name] = {
                    "error": str(e),
                    "class": provider_class.__name__,
                }

        return provider_info

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
    def create_with_fallback(
        cls,
        primary_provider: str,
        fallback_provider: str = "gemini",
    ) -> BaseLLMProvider:
        """
        Create provider with fallback support.

        Args:
            primary_provider: Preferred provider to try first.
            fallback_provider: Fallback provider if primary fails.

        Returns:
            Working LLM provider instance.

        Raises:
            RuntimeError: If both providers fail.
        """
        # Try primary provider
        try:
            service = cls.create_provider(primary_provider, use_cache=False)
            if service.test_connection():
                logger.info(f"Using primary provider: {primary_provider}")
                return service
        except Exception as e:
            logger.warning(f"Primary provider {primary_provider} failed: {e}")

        # Try fallback provider
        try:
            service = cls.create_provider(fallback_provider, use_cache=False)
            if service.test_connection():
                logger.info(f"Using fallback provider: {fallback_provider}")
                return service
        except Exception as e:
            logger.error(f"Fallback provider {fallback_provider} failed: {e}")

        raise RuntimeError(f"Both {primary_provider} and {fallback_provider} providers failed")

    @classmethod
    def clear_cache(cls) -> None:
        """Clear the instance cache."""
        cls._instances.clear()
        logger.debug("Provider instance cache cleared")

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

        # Register OpenAI provider
        try:
            from .openai import OpenAIProvider

            cls.register_provider("openai", OpenAIProvider)
            logger.debug("Registered OpenAI provider")
        except ImportError as e:
            logger.debug(f"OpenAI provider not available: {e}")

        # Register Groq provider
        try:
            from .groq import GroqProvider

            cls.register_provider("groq", GroqProvider)
            logger.debug("Registered Groq provider")
        except ImportError as e:
            logger.debug(f"Groq provider not available: {e}")

        # Register OpenRouter provider
        try:
            from .openrouter import OpenRouterProvider

            cls.register_provider("openrouter", OpenRouterProvider)
            logger.debug("Registered OpenRouter provider")
        except ImportError as e:
            logger.debug(f"OpenRouter provider not available: {e}")


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

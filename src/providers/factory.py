"""O provider LLM da casa: só o Gemini, com o client de `garantis_shared.gemini_backend`."""

import logging
from typing import Optional

from .base import BaseLLMProvider

logger = logging.getLogger(__name__)

#: Um por processo: recriar o provider recria o client e o pool, e anula o keepalive
#: (`models/factory.py`).
_gemini: Optional[BaseLLMProvider] = None


def create_provider(provider: Optional[str] = None) -> BaseLLMProvider:
    """O GeminiProvider do processo.

    `provider` é o nome que o agent ou o request passa. Só `gemini` existe: outro nome é
    erro de quem chamou, e o erro sobe.
    """
    nome = "gemini" if provider is None else provider.lower()
    if nome != "gemini":
        raise ValueError(f"Unsupported provider: {nome}. Available: ['gemini']")

    global _gemini
    if _gemini is None:
        try:
            from .gemini import GeminiProvider

            _gemini = GeminiProvider()
        except ImportError as e:
            raise ImportError(f"Failed to create gemini provider. Missing dependencies: {e}")
        except Exception as e:
            raise RuntimeError(f"Failed to initialize gemini provider: {e}")
        logger.info("Created gemini provider instance")
    return _gemini

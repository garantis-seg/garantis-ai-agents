"""
Factory para criação de clientes de modelos.
"""

import os
from typing import Optional

from google import genai


def create_genai_client(api_key: Optional[str] = None) -> genai.Client:
    """
    Cria um cliente genai configurado.

    Args:
        api_key: API key do Google AI. Se None, usa GOOGLE_API_KEY do ambiente.

    Returns:
        Cliente genai configurado.

    Raises:
        ValueError: Se não houver API key disponível.
    """
    api_key = api_key or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GOOGLE_API_KEY environment variable not set")

    return genai.Client(api_key=api_key)

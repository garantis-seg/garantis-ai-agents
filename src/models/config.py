"""
Configuração de modelos LLM e pricing.
"""

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class ModelPricing:
    """Preço por 1M tokens em USD."""
    input_per_million: float
    output_per_million: float


# Registry de modelos com pricing (atualizado Dez 2025)
# Fonte: https://ai.google.dev/gemini-api/docs/pricing
MODEL_REGISTRY: Dict[str, ModelPricing] = {
    # Gemini 2.5 series
    "gemini-2.5-pro": ModelPricing(1.25, 10.00),
    "gemini-2.5-pro-preview-06-05": ModelPricing(1.25, 10.00),
    "gemini-2.5-flash": ModelPricing(0.15, 0.60),
    "gemini-2.5-flash-preview-05-20": ModelPricing(0.15, 0.60),
    "gemini-2.5-flash-lite": ModelPricing(0.10, 0.40),

    # Gemini 2.0 series
    "gemini-2.0-flash": ModelPricing(0.10, 0.40),
    "gemini-2.0-flash-lite": ModelPricing(0.075, 0.30),
    "gemini-2.0-flash-exp": ModelPricing(0.10, 0.40),

    # Gemini 1.5 series (legacy)
    "gemini-1.5-pro": ModelPricing(1.25, 5.00),
    "gemini-1.5-pro-latest": ModelPricing(1.25, 5.00),
    "gemini-1.5-flash": ModelPricing(0.075, 0.30),
    "gemini-1.5-flash-latest": ModelPricing(0.075, 0.30),
    "gemini-1.5-flash-8b": ModelPricing(0.0375, 0.15),
}

# Modelo padrão
DEFAULT_MODEL = "gemini-2.0-flash"


def get_model_pricing(model: str) -> ModelPricing:
    """
    Retorna pricing para um modelo.

    Args:
        model: Nome do modelo

    Returns:
        ModelPricing com custos por 1M tokens.
    """
    # Tentar match exato
    if model in MODEL_REGISTRY:
        return MODEL_REGISTRY[model]

    # Tentar match por prefixo (ex: "gemini-2.0-flash-exp" -> "gemini-2.0-flash")
    for key in MODEL_REGISTRY:
        if model.startswith(key):
            return MODEL_REGISTRY[key]

    # Fallback para modelo padrão
    return MODEL_REGISTRY[DEFAULT_MODEL]


def calculate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """
    Calcula custo em USD para uma chamada.

    Args:
        model: Nome do modelo
        input_tokens: Número de tokens de input
        output_tokens: Número de tokens de output

    Returns:
        Custo total em USD.
    """
    pricing = get_model_pricing(model)
    return (
        (input_tokens / 1_000_000) * pricing.input_per_million
        + (output_tokens / 1_000_000) * pricing.output_per_million
    )


def list_available_models() -> list:
    """
    Lista todos os modelos disponíveis.

    Returns:
        Lista de nomes de modelos.
    """
    return list(MODEL_REGISTRY.keys())


def get_model_info(model: str) -> Optional[dict]:
    """
    Retorna informações sobre um modelo.

    Args:
        model: Nome do modelo

    Returns:
        Dicionário com informações ou None se não existir.
    """
    if model not in MODEL_REGISTRY:
        return None

    pricing = MODEL_REGISTRY[model]
    return {
        "name": model,
        "input_cost_per_million": pricing.input_per_million,
        "output_cost_per_million": pricing.output_per_million,
    }

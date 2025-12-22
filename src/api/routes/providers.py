"""
Endpoints para gerenciamento de LLM providers.
"""

from typing import Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...providers import LLMFactory, get_available_providers

router = APIRouter(prefix="/providers", tags=["providers"])


class ProviderInfo(BaseModel):
    """Informações de um provider."""
    name: str
    default_model: str
    available_models: List[str]
    supports_structured_output: bool
    supports_async: bool
    status: str  # "available" or "error"
    error: str | None = None


class ProvidersResponse(BaseModel):
    """Resposta da listagem de providers."""
    providers: List[ProviderInfo]
    default_provider: str


class ProviderTestResponse(BaseModel):
    """Resposta do teste de conexão."""
    provider: str
    success: bool
    message: str


@router.get("/", response_model=ProvidersResponse)
async def list_providers():
    """
    Lista todos os LLM providers disponíveis.

    Retorna informações sobre cada provider incluindo
    modelos disponíveis e capacidades.
    """
    providers_info = []

    for provider_name in get_available_providers():
        try:
            provider = LLMFactory.create_provider(provider_name, use_cache=True)
            providers_info.append(
                ProviderInfo(
                    name=provider_name,
                    default_model=provider.get_default_model(),
                    available_models=provider.get_available_models(),
                    supports_structured_output=provider.supports_structured_output(),
                    supports_async=provider.supports_async(),
                    status="available",
                )
            )
        except Exception as e:
            providers_info.append(
                ProviderInfo(
                    name=provider_name,
                    default_model="unknown",
                    available_models=[],
                    supports_structured_output=False,
                    supports_async=False,
                    status="error",
                    error=str(e),
                )
            )

    return ProvidersResponse(
        providers=providers_info,
        default_provider=LLMFactory.get_default_provider(),
    )


@router.get("/{provider_name}", response_model=ProviderInfo)
async def get_provider(provider_name: str):
    """
    Obtém informações de um provider específico.
    """
    if provider_name not in get_available_providers():
        raise HTTPException(
            status_code=404,
            detail=f"Provider '{provider_name}' not found. Available: {get_available_providers()}",
        )

    try:
        provider = LLMFactory.create_provider(provider_name, use_cache=True)
        return ProviderInfo(
            name=provider_name,
            default_model=provider.get_default_model(),
            available_models=provider.get_available_models(),
            supports_structured_output=provider.supports_structured_output(),
            supports_async=provider.supports_async(),
            status="available",
        )
    except Exception as e:
        return ProviderInfo(
            name=provider_name,
            default_model="unknown",
            available_models=[],
            supports_structured_output=False,
            supports_async=False,
            status="error",
            error=str(e),
        )


@router.post("/{provider_name}/test", response_model=ProviderTestResponse)
async def test_provider(provider_name: str):
    """
    Testa a conexão com um provider.
    """
    if provider_name not in get_available_providers():
        raise HTTPException(
            status_code=404,
            detail=f"Provider '{provider_name}' not found. Available: {get_available_providers()}",
        )

    try:
        success = LLMFactory.test_provider(provider_name)
        return ProviderTestResponse(
            provider=provider_name,
            success=success,
            message="Connection successful" if success else "Connection failed",
        )
    except Exception as e:
        return ProviderTestResponse(
            provider=provider_name,
            success=False,
            message=f"Error: {str(e)}",
        )

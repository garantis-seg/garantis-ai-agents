"""
Timing Analysis Agent.

Este agente analisa processos judiciais para identificar oportunidades
de timing para oferta de seguro garantia judicial.

Suporta múltiplos providers (Gemini, OpenAI, Groq, OpenRouter) através
da camada de abstração de providers.
"""

import json
import os
import logging
from typing import Optional

from ...prompts.loader import PromptLoader
from ...providers import LLMFactory, create_provider
from ...providers.base import LLMResponse
from .schemas import LLMResponseV3

logger = logging.getLogger(__name__)

# Configuração padrão
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "gemini-2.0-flash")
DEFAULT_PROMPT_VERSION = os.getenv("DEFAULT_PROMPT_VERSION", "v3")
DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER", "gemini")


async def analyze_timing(
    process_data: str,
    model: Optional[str] = None,
    prompt_version: str = DEFAULT_PROMPT_VERSION,
    provider: str = DEFAULT_PROVIDER,
) -> dict:
    """
    Executa análise de timing usando o provider configurado.

    Args:
        process_data: Dados do processo formatados
        model: Nome do modelo (usa default do provider se None)
        prompt_version: Versão do prompt
        provider: Nome do provider (gemini, openai, groq, openrouter)

    Returns:
        Dicionário com:
        - llm_response: Resposta parseada do LLM (LLMResponseV3)
        - raw_response: Resposta bruta
        - usage: Metadados de uso (tokens, custo, etc)
    """
    # Criar provider
    llm_provider = create_provider(provider)

    # Usar modelo padrão do provider se não especificado
    if model is None:
        model = llm_provider.get_default_model()

    # Carregar prompt com dados do processo
    loader = PromptLoader()
    full_prompt = loader.load(
        "timing_analysis",
        prompt_version,
        process_data=process_data,
    )

    # Chamar provider com schema estruturado
    response: LLMResponse = await llm_provider.agenerate(
        prompt=full_prompt,
        model=model,
        temperature=0.1,
        response_schema=LLMResponseV3,
    )

    # Parse da resposta JSON para o schema
    raw_response = response.text
    try:
        parsed_json = json.loads(raw_response)
        llm_response = LLMResponseV3(**parsed_json)
    except (json.JSONDecodeError, Exception) as e:
        logger.error(f"Failed to parse LLM response: {e}")
        llm_response = None
        parsed_json = {"error": str(e), "raw": raw_response}

    # Extrair usage metadata
    usage = {
        "prompt_tokens": response.input_tokens,
        "completion_tokens": response.output_tokens,
        "total_tokens": response.total_tokens,
        "cost_usd": response.metadata.get("cost_usd", 0.0),
    }

    return {
        "llm_response": llm_response,
        "parsed_json": parsed_json,
        "raw_response": raw_response,
        "usage": usage,
        "model": model,
        "provider": provider,
        "prompt_version": prompt_version,
    }


def analyze_timing_sync(
    process_data: str,
    model: Optional[str] = None,
    prompt_version: str = DEFAULT_PROMPT_VERSION,
    provider: str = DEFAULT_PROVIDER,
) -> dict:
    """
    Versão síncrona da análise de timing.

    Args:
        process_data: Dados do processo formatados
        model: Nome do modelo
        prompt_version: Versão do prompt
        provider: Nome do provider

    Returns:
        Mesmo retorno de analyze_timing.
    """
    # Criar provider
    llm_provider = create_provider(provider)

    if model is None:
        model = llm_provider.get_default_model()

    # Carregar prompt
    loader = PromptLoader()
    full_prompt = loader.load(
        "timing_analysis",
        prompt_version,
        process_data=process_data,
    )

    # Chamar provider (síncrono)
    response: LLMResponse = llm_provider.generate(
        prompt=full_prompt,
        model=model,
        temperature=0.1,
        response_schema=LLMResponseV3,
    )

    # Parse response
    raw_response = response.text
    try:
        parsed_json = json.loads(raw_response)
        llm_response = LLMResponseV3(**parsed_json)
    except (json.JSONDecodeError, Exception) as e:
        logger.error(f"Failed to parse LLM response: {e}")
        llm_response = None
        parsed_json = {"error": str(e), "raw": raw_response}

    usage = {
        "prompt_tokens": response.input_tokens,
        "completion_tokens": response.output_tokens,
        "total_tokens": response.total_tokens,
        "cost_usd": response.metadata.get("cost_usd", 0.0),
    }

    return {
        "llm_response": llm_response,
        "parsed_json": parsed_json,
        "raw_response": raw_response,
        "usage": usage,
        "model": model,
        "provider": provider,
        "prompt_version": prompt_version,
    }


class TimingAnalysisAgent:
    """
    Classe wrapper para o agente de timing analysis.

    Permite configurar modelo, provider e versão do prompt.
    """

    def __init__(
        self,
        model: Optional[str] = None,
        prompt_version: str = DEFAULT_PROMPT_VERSION,
        provider: str = DEFAULT_PROVIDER,
    ):
        """
        Inicializa o agente.

        Args:
            model: Nome do modelo (usa default do provider se None)
            prompt_version: Versão do prompt
            provider: Nome do provider
        """
        self.provider = provider
        self.prompt_version = prompt_version

        # Criar provider para obter modelo padrão se necessário
        llm_provider = create_provider(provider)
        self.model = model or llm_provider.get_default_model()

        logger.info(
            f"TimingAnalysisAgent initialized: provider={provider}, "
            f"model={self.model}, prompt={prompt_version}"
        )

    async def run(self, process_data: str) -> dict:
        """
        Executa a análise de timing.

        Args:
            process_data: Dados do processo formatados

        Returns:
            Resultado da análise
        """
        return await analyze_timing(
            process_data,
            model=self.model,
            prompt_version=self.prompt_version,
            provider=self.provider,
        )

    def run_sync(self, process_data: str) -> dict:
        """
        Versão síncrona de run().

        Args:
            process_data: Dados do processo formatados

        Returns:
            Resultado da análise
        """
        return analyze_timing_sync(
            process_data,
            model=self.model,
            prompt_version=self.prompt_version,
            provider=self.provider,
        )

    def get_config(self) -> dict:
        """Retorna configuração do agente."""
        return {
            "name": "timing_analysis_agent",
            "model": self.model,
            "provider": self.provider,
            "prompt_version": self.prompt_version,
            "description": "Analisa processos judiciais para identificar oportunidades de timing para seguro garantia",
        }


def create_timing_agent(
    model: Optional[str] = None,
    prompt_version: str = DEFAULT_PROMPT_VERSION,
    provider: str = DEFAULT_PROVIDER,
) -> TimingAnalysisAgent:
    """
    Factory function para criar um agente de timing analysis.

    Args:
        model: Nome do modelo
        prompt_version: Versão do prompt
        provider: Nome do provider

    Returns:
        Instância de TimingAnalysisAgent
    """
    return TimingAnalysisAgent(
        model=model,
        prompt_version=prompt_version,
        provider=provider,
    )


# Instância padrão para uso direto
root_agent = TimingAnalysisAgent()

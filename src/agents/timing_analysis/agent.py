"""
Timing Analysis Agent usando Google ADK.

Este agente analisa processos judiciais para identificar oportunidades
de timing para oferta de seguro garantia judicial.
"""

import os
from typing import Optional

from google import genai
from google.genai import types

from ...prompts.loader import PromptLoader
from .schemas import LLMResponseV3


# Configuração padrão
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "gemini-2.0-flash")
DEFAULT_PROMPT_VERSION = os.getenv("DEFAULT_PROMPT_VERSION", "v3")


def get_genai_client():
    """Retorna o cliente genai configurado."""
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GOOGLE_API_KEY environment variable not set")

    return genai.Client(api_key=api_key)


def create_timing_agent_config(
    model: str = DEFAULT_MODEL,
    prompt_version: str = DEFAULT_PROMPT_VERSION,
) -> dict:
    """
    Cria a configuração do agente de timing analysis.

    Args:
        model: Nome do modelo Gemini (ex: "gemini-2.0-flash")
        prompt_version: Versão do prompt (ex: "v3")

    Returns:
        Dicionário com configuração do agente.
    """
    loader = PromptLoader()
    instruction = loader.load("timing_analysis", prompt_version)

    return {
        "name": "timing_analysis_agent",
        "model": model,
        "description": "Analisa processos judiciais para identificar oportunidades de timing para seguro garantia",
        "instruction": instruction,
        "prompt_version": prompt_version,
    }


async def analyze_timing(
    process_data: str,
    model: str = DEFAULT_MODEL,
    prompt_version: str = DEFAULT_PROMPT_VERSION,
) -> dict:
    """
    Executa análise de timing usando o Gemini API diretamente.

    Como o Google ADK ainda está em desenvolvimento e a integração
    com output_schema pode variar, usamos a API genai diretamente
    para garantir controle total sobre a resposta.

    Args:
        process_data: Dados do processo formatados
        model: Nome do modelo Gemini
        prompt_version: Versão do prompt

    Returns:
        Dicionário com:
        - llm_response: Resposta parseada do LLM (LLMResponseV3)
        - raw_response: Resposta bruta
        - usage: Metadados de uso (tokens, etc)
    """
    client = get_genai_client()

    # Carregar prompt com dados do processo
    loader = PromptLoader()
    full_prompt = loader.load(
        "timing_analysis",
        prompt_version,
        process_data=process_data,
    )

    # Configurar geração com response schema
    generation_config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=LLMResponseV3,
    )

    # Chamar API
    response = await client.aio.models.generate_content(
        model=model,
        contents=full_prompt,
        config=generation_config,
    )

    # Extrair resposta
    raw_response = response.text

    # Parse da resposta JSON para o schema
    import json
    try:
        parsed_json = json.loads(raw_response)
        llm_response = LLMResponseV3(**parsed_json)
    except (json.JSONDecodeError, Exception) as e:
        # Fallback: tentar extrair JSON do texto
        llm_response = None
        parsed_json = {"error": str(e), "raw": raw_response}

    # Extrair usage metadata
    usage = None
    if hasattr(response, "usage_metadata") and response.usage_metadata:
        usage = {
            "prompt_tokens": response.usage_metadata.prompt_token_count or 0,
            "candidates_tokens": response.usage_metadata.candidates_token_count or 0,
            "total_tokens": response.usage_metadata.total_token_count or 0,
        }

    return {
        "llm_response": llm_response,
        "parsed_json": parsed_json,
        "raw_response": raw_response,
        "usage": usage,
        "model": model,
        "prompt_version": prompt_version,
    }


def analyze_timing_sync(
    process_data: str,
    model: str = DEFAULT_MODEL,
    prompt_version: str = DEFAULT_PROMPT_VERSION,
) -> dict:
    """
    Versão síncrona da análise de timing.

    Args:
        process_data: Dados do processo formatados
        model: Nome do modelo Gemini
        prompt_version: Versão do prompt

    Returns:
        Mesmo retorno de analyze_timing.
    """
    import asyncio
    return asyncio.run(analyze_timing(process_data, model, prompt_version))


# Para compatibilidade com ADK CLI (adk web)
# O ADK espera um 'root_agent' exportado
class TimingAnalysisAgent:
    """Wrapper do agente para compatibilidade com ADK."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        prompt_version: str = DEFAULT_PROMPT_VERSION,
    ):
        self.model = model
        self.prompt_version = prompt_version
        self.config = create_timing_agent_config(model, prompt_version)

    async def run(self, process_data: str) -> dict:
        """Executa a análise."""
        return await analyze_timing(
            process_data,
            self.model,
            self.prompt_version,
        )


# Instância padrão para ADK
root_agent = TimingAnalysisAgent()

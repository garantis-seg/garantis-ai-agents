"""Processo Synthesis Agent - engine v6_meritos camada 2.

Faz 2 LLM calls em paralelo:
- Call A: synthesis tradicional (estado_processual, decisao_vigente, etc.).
- Call B: probabilidade_exito Daycoval (matriz per tipo_judicial).

Merge no card final. Empirico: combinado num so prompt, gemini-2.5-flash
omitia prob_exito em 100% das tentativas (smoke 1-merito 12151 + 50).
"""

import asyncio
import json
import logging
import os
from typing import Optional

from ...providers import create_provider
from ...providers.base import LLMResponse
from ...utils.llm_json import parse_llm_json
from .prompts import build_probabilidade_exito_prompt, build_processo_synthesis_prompt
from .schemas import ProbabilidadeExito, ProcessoSynthesisCard, ProcessoSynthesisRequest

logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.getenv("PROCESSO_SYNTHESIS_MODEL", "gemini-2.5-flash")
DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER", "gemini")

# Bump quando alterar build_processo_synthesis_prompt, build_probabilidade_exito_prompt
# OU ProcessoSynthesisCard schema. Usado em leads.engine_llm_calls.prompt_version.
#
# v2.1 (2026-05-25, P1+P2 do prompt-engineering FINDINGS):
#   - Adicionado response_schema=ProcessoSynthesisCard / =ProbabilidadeExito nos
#     2 LLM calls (synthesis + prob_exito). Antes so response_mime_type=json.
#   - Removido bloco FORMATO DE SAIDA dos 2 prompts (~80 linhas duplicando shape).
#   - Enriquecido Field(description=...) em schemas.py com semantica que vivia
#     no prompt (decisao_vigente.sentido, risco_processo_intermediario,
#     trajetoria_dentro_processo, peca_pivo_candidata, valores).
#   - REGRA DE LEITURA DE POLOS movida do meio pro TOPO em <regras_criticas>
#     XML. <lembrete_final> no fim como recency anchor.
#   - Tipo-specific blocks (FISCAL/TRABALHISTA/CIVEL) mantidos no meio
#     (sao contextuais por bucket, nao competem com regras universais).
#   - REGRA G ESTABILIDADE TEMPORAL mantida em REGRAS DE OURO (mais tecnica,
#     ligada ao campo decisao_vigente — nao precisa estar no topo).
#
# v2.2 (2026-05-25, proposta L2-only jurisprudencia):
#   - Adicionado campo tese_jurisprudencia no Request (movido de L3 pra L2).
#   - Prompt ganhou bloco <regra_jurisprudencia> dentro de <regras_criticas>
#     no topo + glossario 6 valores resultado_majoritario + REGRAS J/J.1/J.2
#     (adaptadas das G/G.1/G.2 de L3 pro contexto SINGLE processo, modulando
#     risco_processo_intermediario em vez de risco merito agregado).
#   - L3 perdeu juris no payload (Opcao A: single source of truth em L2).
#   - Elimina double-counting: jurisprudencia pesava 2x antes (Matriz Daycoval
#     implicito em L2 + regras G/G.1/G.2 explicitas em L3).
PROMPT_VERSION = "processo_synthesis.v2.2"


async def classify_processo_synthesis(
    request: ProcessoSynthesisRequest | dict,
    model: Optional[str] = None,
    provider: str = DEFAULT_PROVIDER,
) -> dict:
    """Synthesize a processo + classify probabilidade_exito (2 LLM calls em paralelo).

    Returns:
        {"card": ProcessoSynthesisCard.model_dump() | error_dict,
         "raw_response": {"synthesis": ..., "prob_exito": ...},
         "llm_raw_prompt": {"synthesis": str, "prob_exito": str},
         "usage": dict (somando tokens dos 2 calls)}
    """
    if isinstance(request, dict):
        request = ProcessoSynthesisRequest(**request)
    if model is None:
        model = DEFAULT_MODEL

    llm_provider = create_provider(provider)

    synthesis_task = _call_synthesis(llm_provider, request, model, provider)
    prob_exito_task = _call_probabilidade_exito(llm_provider, request, model, provider)
    synthesis_result, prob_exito_result = await asyncio.gather(
        synthesis_task, prob_exito_task,
    )

    card_data = _merge_results(request, synthesis_result, prob_exito_result)
    usage = _merge_usage(synthesis_result["usage"], prob_exito_result["usage"], model, provider)

    return {
        "card": card_data,
        "raw_response": {
            "synthesis": synthesis_result["raw_response"],
            "prob_exito": prob_exito_result["raw_response"],
        },
        "llm_raw_prompt": {
            "synthesis": synthesis_result["prompt"],
            "prob_exito": prob_exito_result["prompt"],
        },
        "prompt_version": PROMPT_VERSION,
        "usage": usage,
    }


async def _call_synthesis(llm_provider, request, model, provider) -> dict:
    """Call A — synthesis sem prob_exito.

    v2.1: response_schema=ProcessoSynthesisCard enforcement (Gemini structured
    output nativo). Antes era so response_mime_type=json. Schema atual tem
    Optional[str] em campos enum (sentido/instancia/natureza) por decisao
    historica — descriptions ricas em Field guiam o LLM.

    Determinismo Bug 4 handoff: temperature=0.0 (era 0.1) + thinking_budget=0
    em gemini-2.5-*. Provider aplica top_p=1.0, top_k=1 quando temp=0.
    """
    prompt = build_processo_synthesis_prompt(request)
    response: LLMResponse = await llm_provider.agenerate(
        prompt=prompt, model=model, temperature=0.0,
        response_schema=ProcessoSynthesisCard,
        thinking_budget=0,
    )
    return {"raw_response": response.text, "prompt": prompt, "usage": _usage_from(response)}


async def _call_probabilidade_exito(llm_provider, request, model, provider) -> dict:
    """Call B — probabilidade_exito Daycoval focused.

    v2.1: response_schema=ProbabilidadeExito enforcement (Gemini structured
    output). Antes era so response_mime_type=json.

    Determinismo Bug 4: temperature=0.0 (era 0.1) + thinking_budget=0.
    """
    prompt = build_probabilidade_exito_prompt(request)
    response: LLMResponse = await llm_provider.agenerate(
        prompt=prompt, model=model, temperature=0.0,
        response_schema=ProbabilidadeExito,
        thinking_budget=0,
    )
    return {"raw_response": response.text, "prompt": prompt, "usage": _usage_from(response)}


def _merge_results(
    request: ProcessoSynthesisRequest,
    synthesis_result: dict,
    prob_exito_result: dict,
) -> dict:
    """Parse + merge synthesis (call A) + prob_exito (call B) num card final.

    Defensive: se call A falhar, retorna error_dict. Se call B falhar, card
    synthesis sai com probabilidade_exito vazio (telemetria warning).
    """
    synthesis_raw = synthesis_result["raw_response"]
    try:
        parsed = parse_llm_json(synthesis_raw)
        parsed.setdefault("processo_numero", request.processo_numero)
        if request.classe and not parsed.get("classe"):
            parsed["classe"] = request.classe
        if request.classe_cnj_code is not None and parsed.get("classe_cnj_code") is None:
            parsed["classe_cnj_code"] = request.classe_cnj_code
        if request.role_no_merito and not parsed.get("role_no_merito"):
            parsed["role_no_merito"] = request.role_no_merito
        parsed["tipo_judicial"] = request.tipo_judicial
        if not parsed.get("movs_processed"):
            parsed["movs_processed"] = len(request.mov_factsheets or [])

        parsed["probabilidade_exito"] = _parse_prob_exito(
            request, prob_exito_result["raw_response"],
        )

        card = ProcessoSynthesisCard(**parsed)
        return card.model_dump()
    except (json.JSONDecodeError, Exception) as e:
        logger.error(
            "processo_synthesis parse failed pn=%s: %s | raw_first_800=%s",
            request.processo_numero, repr(e), (synthesis_raw or "")[:800],
        )
        return {
            "error": repr(e), "raw": synthesis_raw,
            "processo_numero": request.processo_numero,
        }


def _parse_prob_exito(
    request: ProcessoSynthesisRequest, raw_response: str,
) -> dict:
    """Parse call B output. Defaults vazios se LLM omitiu/falhou — caller
    (merito_synthesis aggregator) trata classificacao=null como sem-sinal."""
    try:
        parsed = parse_llm_json(raw_response)
        pe = ProbabilidadeExito(**parsed)
        result = pe.model_dump()
        if not result.get("classificacao"):
            logger.warning(
                "probabilidade_exito pn=%s OMITIDO pelo LLM (tipo=%s, movs=%d)",
                request.processo_numero, request.tipo_judicial,
                len(request.mov_factsheets or []),
            )
        return result
    except (json.JSONDecodeError, Exception) as e:
        logger.warning(
            "prob_exito parse failed pn=%s: %s | raw_first_400=%s",
            request.processo_numero, repr(e), (raw_response or "")[:400],
        )
        return ProbabilidadeExito().model_dump()


def _usage_from(response: LLMResponse) -> dict:
    return {
        "input_tokens": response.input_tokens or 0,
        "output_tokens": response.output_tokens or 0,
        "cost_usd": (response.metadata.get("cost_usd", 0.0) if response.metadata else 0.0),
    }


def _merge_usage(
    usage_a: dict, usage_b: dict, model: str, provider: str,
) -> dict:
    """Soma os 2 calls + adiciona model/provider."""
    return {
        "input_tokens": usage_a["input_tokens"] + usage_b["input_tokens"],
        "output_tokens": usage_a["output_tokens"] + usage_b["output_tokens"],
        "total_tokens": (
            usage_a["input_tokens"] + usage_b["input_tokens"]
            + usage_a["output_tokens"] + usage_b["output_tokens"]
        ),
        "cost_usd": usage_a["cost_usd"] + usage_b["cost_usd"],
        "model": model,
        "provider": provider,
        "calls": 2,
        # L2 sempre text — não tem Vision path (consume cards L1, não docs raw).
        "model_variant": "text",
    }

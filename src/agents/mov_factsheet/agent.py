"""Mov FactSheet Agent — engine v6_meritos camada 1.

Single LLM call por movimentacao, extrai 13 campos estruturados.
Substitui mov_summarizer durante coexistencia (kind='mov_factsheet' vs kind='movimentacao').
"""

import json
import logging
import os
from typing import Optional

from ...providers import create_provider
from ...providers.base import LLMResponse
from ...utils.llm_json import parse_llm_json
from .prompts import build_mov_factsheet_prompt
from .schemas import (
    DocAnexado,
    FallbackContext,
    MovFactSheetCard,
    MovInput,
    ProcessoContext,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.getenv("MOV_FACTSHEET_MODEL", "gemini-2.5-flash-lite")
DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER", "gemini")

# Bump quando alterar build_mov_factsheet_prompt OR MovFactSheetCard schema.
# Usado pra drift detection em leads.engine_llm_calls.prompt_version.
#
# v2.0 (2026-05-25, P1 do prompt-engineering FINDINGS):
#   - Removido bloco FORMATO DE SAIDA do prompt (duplicava response_schema).
#   - Enriquecido Field(description=...) em schemas.py com semantica que vivia
#     no prompt. Cada campo carrega sua propria guidance via JSON Schema.
#   - Schema enforcement Gemini cobre estrutura. Prompt cobre semantica do
#     dominio + regras criticas (POLOS, RECURSOS, EXTINCAO).
#
# v2.1 (2026-05-25, P2 do prompt-engineering FINDINGS):
#   - REGRA DE LEITURA DE POLOS + REGRA RECURSOS + REGRA EXTINCAO movidas do
#     meio pro TOPO em <regras_criticas> XML. Combate Lost-in-the-Middle.
#   - <lembrete_final> no fim como recency anchor pras 3 regras criticas.
#   - Eliminado bloco duplicado "REGRA DURA EXTINCAO" dentro de INSTRUCOES POR
#     CAMPO (single source of truth: <regra_extincao_sem_merito>).
#
# v2.2 (2026-05-25, polo-regression suite detectou contradicao L1 vs L2):
#   - <regra_extincao_sem_merito> ENRIQUECIDA com EXCECAO Tomador-AUTOR.
#     Antes L1 sempre forçava sentido='neutro' em extincao_sem_merito. MAS L2
#     prompt v2.2 ja tinha <regra_extincao_tomador_autor> dizendo o OPOSTO
#     pra classes Tomador-autor (Anulatoria/MS/Tutela Cautelar Antecedente/
#     Embargos): sentido='desfavoravel'. Resultava em contradicao silenciosa
#     onde card L1 marcava neutro e L2 corrigia pra desfavoravel.
#   - Fix: L1 agora aplica mesma regra que L2 — DEFAULT neutro pra classes
#     Tomador-reu, EXCECAO desfavoravel pra classes Tomador-autor. Caso
#     paradigma: Tutela Cautelar Antecedente extinta por perda de objeto
#     (CPC 308) = sentido='desfavoravel' (Tomador perdeu).
PROMPT_VERSION = "mov_factsheet.v2.2"


async def classify_mov_factsheet(
    processo: ProcessoContext | dict,
    mov: MovInput | dict,
    documentos_anexados: list[DocAnexado | dict] | None = None,
    fallback_context: FallbackContext | dict | None = None,
    model: Optional[str] = None,
    provider: str = DEFAULT_PROVIDER,
) -> dict:
    """Extract a 13-field FactSheet from a single mov.

    Args:
        processo: contexto minimo (CNJ, classe, polos)
        mov: id + data + tipo + texto da publicacao (snippet DJe)
        documentos_anexados: docs vinculados a essa mov (rota com doc text)
        fallback_context: passado SOMENTE quando documentos_anexados vazio
        model: override Gemini model
        provider: 'gemini' (default)

    Returns:
        {"card": MovFactSheetCard.model_dump() | error_dict,
         "raw_response": str,
         "llm_raw_prompt": str,
         "usage": dict}
    """
    if isinstance(processo, dict):
        processo = ProcessoContext(**processo)
    if isinstance(mov, dict):
        mov = MovInput(**mov)

    docs_typed: list[DocAnexado] = []
    for d in documentos_anexados or []:
        docs_typed.append(d if isinstance(d, DocAnexado) else DocAnexado(**d))

    fb_typed: FallbackContext | None = None
    if fallback_context is not None:
        fb_typed = (
            fallback_context
            if isinstance(fallback_context, FallbackContext)
            else FallbackContext(**fallback_context)
        )

    if model is None:
        model = DEFAULT_MODEL

    llm_provider = create_provider(provider)
    prompt = build_mov_factsheet_prompt(
        processo, mov,
        documentos_anexados=docs_typed,
        fallback_context=fb_typed,
    )

    response: LLMResponse = await llm_provider.agenerate(
        prompt=prompt,
        model=model,
        temperature=0.0,
        response_schema=MovFactSheetCard,
        # Determinismo Bug 4 handoff: greedy strict + thinking OFF em gemini-2.5-*.
        # Provider aplica top_p=1.0, top_k=1 automaticamente quando temperature=0.
        thinking_budget=0,
    )

    raw_response = response.text
    try:
        parsed = parse_llm_json(raw_response)
        # Echo input identifiers em caso de LLM reset
        parsed.setdefault("mov_id", mov.mov_id)
        if mov.data and not parsed.get("data"):
            parsed["data"] = mov.data
        if mov.tipo and not parsed.get("tipo_origem"):
            parsed["tipo_origem"] = mov.tipo
        card = MovFactSheetCard(**parsed)
        card_data = card.model_dump()
    except (json.JSONDecodeError, Exception) as e:
        logger.error(f"mov_factsheet parse failed mov_id={mov.mov_id}: {repr(e)}")
        card_data = {"error": repr(e), "raw": raw_response, "mov_id": mov.mov_id}

    usage = {
        "input_tokens": response.input_tokens or 0,
        "output_tokens": response.output_tokens or 0,
        "total_tokens": (response.input_tokens or 0) + (response.output_tokens or 0),
        "cost_usd": (response.metadata.get("cost_usd", 0.0) if response.metadata else 0.0),
        "model": model,
        "provider": provider,
    }

    return {
        "card": card_data,
        "raw_response": raw_response,
        "llm_raw_prompt": prompt,
        "prompt_version": PROMPT_VERSION,
        "usage": usage,
    }

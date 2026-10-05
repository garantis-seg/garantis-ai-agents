"""Mov Triage Agent — L1 v7, 1o estagio do desenho de 2 estagios.

UMA chamada LLM BARATA (prompt curto, modelo lite de DEFAULT_MODEL, temperature=0) que
responde os campos baratos + 2 PORTOES de roteamento:
  P1 mov_merito       — o ato decide algo OU traz tese/pedido/prova/desfecho?
  P2 mov_garantia_exec — toca garantia/apolice/deposito/acionamento OU avanca
                         execucao contra o Tomador? (REGRA DURA: na duvida true)

ROTEAMENTO (decidido pelo caller, NAO aqui): P1 ou P2 = true -> passe COMPLETO
(/mov-factsheet/classify). P1 e P2 = false -> ENXUTO (deriva o card por codigo).

Espelha classify_mov_factsheet, mas com prompt/schema da triagem e SEM o caminho
Vision (a triagem e text-only por design — roteamento barato). Fail-safe: card
malformado -> error dict, e o caller trata como "precisa completo".
"""

import json
import logging
import os
import pathlib
from typing import Optional

from ...providers import create_provider
from ...providers.base import LLMResponse
from ...utils.llm_json import parse_llm_json
from .._utils import MODEL_VARIANT_TEXT
from .._utils.prompt_identity import versao_com_identidade
from ..mov_factsheet.agent import _resumo_looks_like_json_meta_leak
from .prompts import build_mov_triage_prompt
from .schemas import (
    DocAnexado,
    FallbackContext,
    MovInput,
    MovTriageCard,
    ProcessoContext,
)

logger = logging.getLogger(__name__)

# Triagem roda SEMPRE no modelo mais barato — e o ponto do 1o estagio.
# NUNCA usar gemini-3.1-flash NAO-lite — nao existe no Vertex (404).
DEFAULT_MODEL = os.getenv("MOV_TRIAGE_MODEL", "gemini-3.1-flash-lite")
DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER", "gemini")

# ⭐ DERIVADA, nao mantida a mao — razao em `_utils/prompt_identity.py`. A triagem e a
# UNICA provenance de boa parte dos cards L1 (o ramo enxuto nao gera row em
# layer1_mov_factsheet): rotulo que nao se move aqui cega a deteccao de drift na camada
# que decide o que as outras chegam a ver.
#
# ⭐⭐ `agent.py` ENTRA NO CONJUNTO: `prompts.py` e `schemas.py` quase nunca mudam, e
# hashear so os dois daria um id CONSTANTE — a mesma informacao que o rotulo que ele
# substitui. E o `agent.py` muda o que o card EMITE: o leak guard de `resumo_ato`
# SOBRESCREVE pos-LLM um dos 3 campos que o ramo enxuto copia verbatim da triagem, e o
# modelo default mora aqui.
# ⚠️ Isto inclui este proprio arquivo, entao edicao aqui que NAO muda a saida tambem bumpa.
# E ruido barato e da classe que o `prompt_identity.py` abencoa ("sobre-sensivel na direcao
# segura"): dois prompts diferentes nunca dividem um id.
#
# ⛔ NAO incluir arquivo do `mov_factsheet`: o `schemas.py` daqui importa os tipos de INPUT
# de la, mas input nao molda saida, e incluir faria uma edicao no L1 completo acusar mudanca
# na triagem (`tests/test_prompt_identity.py` guarda as 3 identidades separadas).
# ⭐ Ninguem casa este valor por LITERAL — ao contrario de `PETICAO_PROMPT_VERSION`
# (garantis-shared), que e chave de ROLLOUT do `reextract_stale` e fica congelada.
PROMPT_VERSION = versao_com_identidade(
    "mov_triage.v1",
    str(pathlib.Path(__file__).with_name("prompts.py")),
    str(pathlib.Path(__file__).with_name("schemas.py")),
    __file__,
)


async def classify_mov_triage(
    processo: ProcessoContext | dict,
    mov: MovInput | dict,
    documentos_anexados: list[DocAnexado | dict] | None = None,
    fallback_context: FallbackContext | dict | None = None,
    model: Optional[str] = None,
    provider: str = DEFAULT_PROVIDER,
) -> dict:
    """Triagem barata de UMA movimentacao. 1 LLM call, 6 campos.

    Args:
        processo: contexto minimo (CNJ, classe, polos)
        mov: id + data + tipo + texto da publicacao (snippet DJe)
        documentos_anexados: docs vinculados a essa mov
        fallback_context: paridade de assinatura com o factsheet (nao consumido)
        model: override Gemini model (default DEFAULT_MODEL)
        provider: 'gemini' (default)

    Returns:
        {"card": MovTriageCard.model_dump() | error_dict,
         "raw_response": str,
         "llm_raw_prompt": str,
         "prompt_version": str,
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
    prompt = build_mov_triage_prompt(
        processo, mov,
        documentos_anexados=docs_typed,
        fallback_context=fb_typed,
    )

    # Triagem e text-only por design (roteamento barato, sem Vision).
    response: LLMResponse = await llm_provider.agenerate(
        prompt=prompt,
        model=model,
        temperature=0.0,
        response_schema=MovTriageCard,
        thinking_budget=0,
    )

    raw_response = response.text
    try:
        parsed = parse_llm_json(raw_response)
        card = MovTriageCard(**parsed)
        card_data = card.model_dump()
    except (json.JSONDecodeError, Exception) as e:
        logger.error(f"mov_triage parse failed mov_id={mov.mov_id}: {repr(e)}")
        card_data = {"error": repr(e), "raw": raw_response, "mov_id": mov.mov_id}

    # Leak guard: mesma degeneração do mov_factsheet — JSON válido cujo VALOR
    # de resumo_ato é o meta-erro/inglês do modelo. Troca pelo TEXTO CRU do evento e mantém
    # o card. Não pode ser None (schema str -> ValidationError->500->engine retenta 6x à
    # toa) nem erro (idem). Esses movs degeneram em flash-lite E flash.
    if (isinstance(card_data, dict) and not card_data.get("error")
            and _resumo_looks_like_json_meta_leak(card_data.get("resumo_ato"))):
        logger.warning(
            "L1_TRIAGE_RESUMO_META_LEAK mov_id=%s -> texto cru (card mantido)",
            mov.mov_id,
        )
        card_data["resumo_ato"] = (getattr(mov, "texto", "") or "").strip()[:500] or "(resumo indisponivel)"

    usage = {
        "input_tokens": response.input_tokens or 0,
        "output_tokens": response.output_tokens or 0,
        "total_tokens": (response.input_tokens or 0) + (response.output_tokens or 0),
        "cached_tokens": getattr(response, "cached_tokens", 0) or 0,
        "cost_usd": (response.metadata.get("cost_usd", 0.0) if response.metadata else 0.0),
        "model": model,
        "provider": provider,
        "model_variant": (
            response.metadata.get("model_variant", MODEL_VARIANT_TEXT)
            if response.metadata else MODEL_VARIANT_TEXT
        ),
    }

    return {
        "card": card_data,
        "raw_response": raw_response,
        "llm_raw_prompt": prompt,
        "prompt_version": PROMPT_VERSION,
        "usage": usage,
    }

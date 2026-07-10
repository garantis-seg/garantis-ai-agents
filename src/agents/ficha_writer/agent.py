"""ficha_writer agent — escreve os slots de texto de uma ficha (FichaJSON v2).

Stateless. Usa o factory (provider default = Gemini) em JSON mode (dynamic
schema -> response_mime_type, NAO response_schema estatico, pois os slots variam
por request). Parseia a saida, valida que CADA slot pedido esta presente e e
STRING, e propaga cost_usd/model do LLMResponse.

Slots ACHATADOS: todo valor e string simples ("bullets[0]", "merito.p1", ...).
Retry cirurgico: quando campos_com_erro esta presente, gera/corrige SO os slots
listados la (specs em request.campos) e responde SO com eles.

Validacao LEVE: se um slot faltar ou nao vier string, retorna success=false com
error claro — o caller decide o retry. NAO valida limite de chars (`max`) aqui
(a validacao dura e do caller); o limite entra no PROMPT.
"""

import logging
import os
from typing import Optional

from ...providers import create_provider
from ...providers.base import LLMResponse
from ...utils.llm_json import parse_llm_json
from .prompts import build_write_fields_prompt
from .schemas import CampoSpec, FichaWriteFieldsRequest, FichaWriteFieldsResponse

logger = logging.getLogger(__name__)

DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER", "gemini")
DEFAULT_MODEL = os.getenv("FICHA_WRITER_MODEL", os.getenv("DEFAULT_MODEL", "gemini-2.5-flash"))


def _resolve_campos_alvo(
    request: FichaWriteFieldsRequest,
) -> tuple[Optional[list[CampoSpec]], Optional[str]]:
    """Resolve os slots ALVO da chamada.

    Sem campos_com_erro -> todos os request.campos. Com campos_com_erro (retry)
    -> SO os slots com erro, na ordem de campos_com_erro, usando os specs de
    request.campos. Se um nome com erro nao tem spec, retorna erro (contrato
    quebrado pelo caller).
    """
    if not request.campos_com_erro:
        return list(request.campos), None
    by_nome = {c.nome: c for c in request.campos}
    alvo: list[CampoSpec] = []
    for ce in request.campos_com_erro:
        spec = by_nome.get(ce.nome)
        if spec is None:
            return None, f"campo_com_erro '{ce.nome}' sem spec correspondente em `campos`"
        alvo.append(spec)
    return alvo, None


def _extract_and_validate(
    parsed: dict, campos: list[CampoSpec]
) -> tuple[Optional[dict[str, str]], Optional[str]]:
    """Extrai EXATAMENTE os slots pedidos do JSON do LLM, exigindo string em
    cada um. Retorna (campos_dict, None) em sucesso ou (None, erro) na 1a falha.

    Nao valida `max` (validacao dura = caller); so presenca + tipo string.
    """
    out: dict[str, str] = {}
    for spec in campos:
        if spec.nome not in parsed:
            return None, f"campo ausente na resposta do LLM: '{spec.nome}'"
        val = parsed[spec.nome]
        if not isinstance(val, str):
            return None, f"campo '{spec.nome}' deveria ser string, veio {type(val).__name__}"
        out[spec.nome] = val
    return out, None


async def write_ficha_fields(
    request: FichaWriteFieldsRequest | dict,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> FichaWriteFieldsResponse:
    """Escreve os slots de texto pedidos a partir do dossie.

    Retorna FichaWriteFieldsResponse. Em qualquer falha (parse/slot faltando/
    nao-string) devolve success=false + error claro (nunca levanta, p/ o caller
    decidir o retry) — mas propaga model/cost_usd mesmo no erro.
    """
    if isinstance(request, dict):
        request = FichaWriteFieldsRequest(**request)

    provider = provider or request.provider or DEFAULT_PROVIDER
    model = model or request.model or DEFAULT_MODEL

    campos_alvo, err = _resolve_campos_alvo(request)
    if err is not None:
        return FichaWriteFieldsResponse(
            success=False, campos={}, model=model, cost_usd=0.0, error=err,
        )

    llm_provider = create_provider(provider)
    prompt = build_write_fields_prompt(request, campos_alvo=campos_alvo)

    response: LLMResponse = await llm_provider.agenerate(
        prompt=prompt,
        model=model,
        temperature=0.0,
        response_mime_type="application/json",  # JSON mode SEM schema estatico (slots dinamicos)
        thinking_budget=0,
        max_tokens=8192,
    )
    raw = response.text or ""
    used_model = response.model or model
    cost_usd = (response.metadata.get("cost_usd", 0.0) if response.metadata else 0.0)

    try:
        parsed = parse_llm_json(raw)
    except (ValueError, Exception) as e:  # noqa: BLE001
        logger.warning("FICHA_WRITER_PARSE_FAIL: %r | head=%r", e, raw[:200])
        return FichaWriteFieldsResponse(
            success=False,
            campos={},
            model=used_model,
            cost_usd=cost_usd,
            error=f"parse do JSON do LLM falhou: {e}",
        )

    campos, err = _extract_and_validate(parsed, campos_alvo)
    if err is not None:
        logger.info("FICHA_WRITER_VALIDATION_FAIL: %s", err)
        return FichaWriteFieldsResponse(
            success=False,
            campos={},
            model=used_model,
            cost_usd=cost_usd,
            error=err,
        )

    return FichaWriteFieldsResponse(
        success=True,
        campos=campos,
        model=used_model,
        cost_usd=cost_usd,
        error=None,
    )


__all__ = ["write_ficha_fields"]

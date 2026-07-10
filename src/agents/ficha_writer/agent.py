"""ficha_writer agent — escreve os slots de texto de uma ficha (FichaJSON v2).

Stateless. Usa o factory (provider default = Gemini) em JSON mode (dynamic
schema -> response_mime_type, NAO response_schema estatico, pois os campos variam
por request). Parseia a saida, valida presenca+tipo de CADA campo pedido e
propaga cost_usd/model do LLMResponse.

Validacao LEVE: se um campo faltar ou vier no tipo errado, retorna success=false
com error claro — o caller decide o retry. NAO valida limite de chars aqui (a
validacao dura e do caller); o limite entra no PROMPT.
"""

import logging
import os
from typing import Any, Optional

from ...providers import create_provider
from ...providers.base import LLMResponse
from ...utils.llm_json import parse_llm_json
from .prompts import build_write_fields_prompt
from .schemas import CampoSpec, FichaWriteFieldsRequest, FichaWriteFieldsResponse

logger = logging.getLogger(__name__)

DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER", "gemini")
DEFAULT_MODEL = os.getenv("FICHA_WRITER_MODEL", os.getenv("DEFAULT_MODEL", "gemini-2.5-flash"))


def _coerce_and_validate(parsed: dict, campos: list[CampoSpec]) -> tuple[Optional[dict], Optional[str]]:
    """Extrai EXATAMENTE os campos pedidos do JSON do LLM, validando o tipo de
    cada um. Retorna (campos_dict, None) em sucesso ou (None, erro) na 1a falha.

    Nao valida limite_chars (validacao dura = caller); so shape/tipo/presenca.
    """
    out: dict[str, Any] = {}
    for spec in campos:
        if spec.nome not in parsed:
            return None, f"campo ausente na resposta do LLM: '{spec.nome}'"
        val = parsed[spec.nome]

        if spec.tipo == "string":
            if not isinstance(val, str):
                return None, f"campo '{spec.nome}' deveria ser string, veio {type(val).__name__}"
            out[spec.nome] = val

        elif spec.tipo == "array_string":
            if not isinstance(val, list) or not all(isinstance(x, str) for x in val):
                return None, f"campo '{spec.nome}' deveria ser lista de strings"
            out[spec.nome] = val

        elif spec.tipo == "objeto_p1_p2":
            if (
                not isinstance(val, dict)
                or not isinstance(val.get("p1"), str)
                or not isinstance(val.get("p2"), str)
            ):
                return None, f"campo '{spec.nome}' deveria ser objeto {{p1: str, p2: str}}"
            out[spec.nome] = {"p1": val["p1"], "p2": val["p2"]}

        else:  # defensivo — schema ja restringe o Literal
            return None, f"tipo desconhecido '{spec.tipo}' no campo '{spec.nome}'"

    return out, None


async def write_ficha_fields(
    request: FichaWriteFieldsRequest | dict,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> FichaWriteFieldsResponse:
    """Escreve os slots de texto pedidos a partir do dossie.

    Retorna FichaWriteFieldsResponse. Em qualquer falha (parse/tipo/campo
    faltando) devolve success=false + error claro (nunca levanta p/ o caller
    decidir o retry) — mas propaga model/cost_usd mesmo no erro.
    """
    if isinstance(request, dict):
        request = FichaWriteFieldsRequest(**request)

    provider = provider or request.provider or DEFAULT_PROVIDER
    model = model or request.model or DEFAULT_MODEL

    llm_provider = create_provider(provider)
    prompt = build_write_fields_prompt(request)

    response: LLMResponse = await llm_provider.agenerate(
        prompt=prompt,
        model=model,
        temperature=0.0,
        response_mime_type="application/json",  # JSON mode SEM schema estatico (campos dinamicos)
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

    campos, err = _coerce_and_validate(parsed, request.campos)
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

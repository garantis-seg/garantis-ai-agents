"""Agente AUDITOR DE EVIDENCIAS (C4) — julga se cada trecho sustenta o valor.

Stateless. Modelo DIFERENTE do calculador por default (configuravel): auditar
com o mesmo modelo que calculou e pedir a alguem que revise o proprio trabalho
— os erros sao correlacionados e se confirmam mutuamente.

Duas travas de fail-safe, ambas na direcao de REPROVAR:

1. **Veredicto faltando = reprovado.** Se o modelo omite uma evidencia, o
   agente sintetiza um veredicto negativo. Omissao nunca vira aprovacao
   silenciosa — seria a forma mais barata de o gate ser contornado.
2. **Falha do agente nao aprova nada.** Parse quebrado, timeout ou resposta
   malformada devolvem `success=false`, e o harness trata como rejeicao da
   rodada.
"""

import logging
import os
from typing import Any, Optional

from ...providers import create_provider
from ...providers.base import LLMResponse
from ...utils.llm_json import parse_llm_json
from .prompts import build_auditar_prompt
from .schemas import AuditarEvidenciasRequest, AuditarEvidenciasResponse, Veredicto

logger = logging.getLogger(__name__)

DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER", "gemini")

#: Modelo do AUDITOR — deliberadamente distinto do CALCULO_FICHA_MODEL.
#: Configuravel para que a casa possa cruzar familias de modelo (o ideal e
#: provider diferente, nao so versao diferente).
DEFAULT_MODEL = os.getenv(
    "AUDITOR_EVIDENCIAS_MODEL", os.getenv("DEFAULT_MODEL", "gemini-2.5-flash")
)

_MOTIVO_OMISSO = (
    "auditor nao emitiu veredicto para esta evidencia — reprovada por omissao "
    "(silencio nunca vale aprovacao)"
)


def _normalizar_veredictos(
    parsed: dict, evidencias: list[dict[str, Any]]
) -> tuple[list[dict], Optional[str]]:
    """Casa os veredictos com as evidencias pedidas, reprovando o que faltar.

    Veredicto para celula que nao foi pedida e descartado (ruido do modelo);
    evidencia sem veredicto vira reprovacao. O resultado tem SEMPRE exatamente
    um veredicto por evidencia, na ordem das evidencias.
    """
    brutos = parsed.get("veredictos")
    if not isinstance(brutos, list):
        return [], f"resposta sem lista `veredictos` (veio {type(brutos).__name__})"

    por_id: dict[str, dict] = {}
    for v in brutos:
        if not isinstance(v, dict):
            continue
        try:
            modelo = Veredicto(**v)
        except Exception:  # noqa: BLE001 — veredicto malformado nao aprova
            continue
        # Reprovacao sem motivo nao ajuda o calculador a corrigir.
        if not modelo.aprovada and not modelo.motivo.strip():
            modelo = Veredicto(
                celula_id=modelo.celula_id, aprovada=False,
                motivo="auditor reprovou sem declarar motivo",
            )
        por_id[modelo.celula_id] = modelo.model_dump()

    out: list[dict] = []
    for e in evidencias:
        cid = str(e.get("celula_id", ""))
        out.append(por_id.get(cid) or {
            "celula_id": cid, "aprovada": False, "motivo": _MOTIVO_OMISSO,
        })
    return out, None


async def auditar_evidencias(
    request: AuditarEvidenciasRequest | dict,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> AuditarEvidenciasResponse:
    """Julga cada evidencia: o trecho sustenta o valor da celula?

    Nunca levanta: falha vira `success=false` + error, que o harness registra
    como rejeicao da rodada (falha do auditor nao e aprovacao).
    """
    if isinstance(request, dict):
        request = AuditarEvidenciasRequest(**request)

    provider = provider or request.provider or DEFAULT_PROVIDER
    model = model or request.model or DEFAULT_MODEL

    if not request.evidencias:
        return AuditarEvidenciasResponse(
            success=False, model=model, cost_usd=0.0,
            error="nenhuma evidencia para auditar",
        )

    llm_provider = create_provider(provider)
    prompt = build_auditar_prompt(request)

    response: LLMResponse = await llm_provider.agenerate(
        prompt=prompt,
        model=model,
        temperature=0.0,
        response_mime_type="application/json",
        max_tokens=8192,
    )
    raw = response.text or ""
    used_model = response.model or model
    cost_usd = (response.metadata.get("cost_usd", 0.0) if response.metadata else 0.0)

    try:
        parsed = parse_llm_json(raw)
    except Exception as e:  # noqa: BLE001
        logger.warning("AUDITOR_EVIDENCIAS_PARSE_FAIL: %r | head=%r", e, raw[:200])
        return AuditarEvidenciasResponse(
            success=False, model=used_model, cost_usd=cost_usd,
            error=f"parse do JSON do LLM falhou: {e}",
        )

    veredictos, err = _normalizar_veredictos(parsed, request.evidencias)
    if err is not None:
        logger.info("AUDITOR_EVIDENCIAS_VALIDATION_FAIL: %s", err)
        return AuditarEvidenciasResponse(
            success=False, model=used_model, cost_usd=cost_usd, error=err,
        )

    reprovadas = sum(1 for v in veredictos if not v["aprovada"])
    logger.info(
        "AUDITOR_EVIDENCIAS_OK total=%d reprovadas=%d model=%s",
        len(veredictos), reprovadas, used_model,
    )
    return AuditarEvidenciasResponse(
        success=True, veredictos=veredictos, model=used_model,
        cost_usd=cost_usd, error=None,
    )


__all__ = ["auditar_evidencias"]

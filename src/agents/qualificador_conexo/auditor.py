"""Auditor da S2c — um segundo modelo tenta refutar cada prova.

O auditor recebe SÓ as afirmações e as provas. Ele não vê o conexo, o índice,
nem o que o qualificador leu. Ele audita 3 tipos de afirmação:

- cada processo com `e_fiscal=false`;
- cada garantia com `estado` substituida ou liberada;
- cada alerta `refutado`.

Afirmação sem prova (modo capa) não vai ao auditor: ela já sai com
`requer_revisao=true`.

Silêncio não aprova. Afirmação sem veredito, ou auditor que falhou, conta como
divergência.

Sem 3ª leitura por ora: o plano (Parte 3, S2c) pede uma leitura dirigida à
página citada quando há divergência. 22/10/2026: a divergência só rebaixa a
`confianca` para `baixa` e marca `requer_revisao=true`. A 3ª leitura entra
quando os 15 casos mostrarem a taxa de divergência.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from garantis_shared.llm_models import model_for
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ...utils.llm_json import parse_llm_json
from .._utils.llm_seed import seed_for
from .prompts import build_auditor_prompt
from .schemas import MAX_MOTIVO

logger = logging.getLogger(__name__)

#: Regra anti-conluio: quem confere não é da família de quem respondeu.
#: 22/10/2026: papéis provisórios; pedido ao Elton de `ficha_qualificador` e
#: `ficha_auditor_qualificacao` no registro (card 869ffv22t).
DEFAULT_MODEL = model_for("ficha_auditoria_evidencias")

_TENTATIVAS = 2


class _Veredito(BaseModel):
    model_config = ConfigDict(extra="forbid")
    afirmacao_id: str
    sustenta: bool
    motivo: str = Field(default="", max_length=MAX_MOTIVO)


class _Vereditos(BaseModel):
    model_config = ConfigDict(extra="forbid")
    vereditos: list[_Veredito]


def _truncar_motivos(parsed: Any) -> Any:
    """Corta `motivo` no teto antes da validação.

    Um motivo longo não muda o veredito. Reprovar o auditor inteiro por isso
    jogaria todas as afirmações em divergência sem razão.
    """
    if isinstance(parsed, dict):
        for v in parsed.get("vereditos") or []:
            if isinstance(v, dict) and isinstance(v.get("motivo"), str):
                v["motivo"] = v["motivo"][:MAX_MOTIVO]
    return parsed


async def auditar(
    afirmacoes: list[dict[str, Any]],
    llm: Any,
    conexo_id: Any,
) -> tuple[dict[str, tuple[bool, str]], float, str, int, Optional[str]]:
    """Devolve `(vereditos, custo, modelo, chamadas_llm, erro)`.

    `vereditos` = `{afirmacao_id: (sustenta, motivo)}`. Com `erro`, os
    vereditos vêm vazios, e o chamador conta toda afirmação como divergência.
    """
    custo = 0.0
    modelo = DEFAULT_MODEL
    chamadas = 0
    erro: Optional[str] = None
    for tentativa in range(1, _TENTATIVAS + 1):
        resp = await llm.agenerate(
            prompt=build_auditor_prompt(afirmacoes),
            model=DEFAULT_MODEL,
            temperature=0.0,
            max_tokens=4096,
            response_mime_type="application/json",
            seed=seed_for("qualificador_conexo_auditor", conexo_id, tentativa),
        )
        chamadas += 1
        custo += float((resp.metadata or {}).get("cost_usd", 0.0) or 0.0)
        modelo = resp.model or modelo
        try:
            parsed = _truncar_motivos(parse_llm_json(resp.text or ""))
            vereditos = _Vereditos.model_validate(parsed)
        except (ValueError, ValidationError) as e:
            erro = f"auditor devolveu JSON inválido: {e}"
            logger.info("QUALIFICADOR_AUDITOR_INVALIDO t=%d: %s", tentativa, erro)
            continue
        return (
            {v.afirmacao_id: (v.sustenta, v.motivo) for v in vereditos.vereditos},
            custo, modelo, chamadas, None,
        )
    return {}, custo, modelo, chamadas, erro


__all__ = ["DEFAULT_MODEL", "auditar"]

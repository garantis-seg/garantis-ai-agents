"""L2 PROSA — passe de redacao da justificativa (engine v6, 2026-06-28).

"Codigo decide o risco, LLM redige." O risco JA foi decidido (holistico +
guards determ.) e entra FIXO em RedacaoRequest.risco_final; este passe so
VERBALIZA a prosa, aplicando o <filtro_redacao_advogado> do socio VERBATIM
(prompts._build_filtro_redacao). Como o LLM nao classifica, a consistencia
risco<->prosa e garantida por construcao.

Guard runtime (prose_lint): se a saida vaza jargao List-B, 1 retry ecoando os
trechos vazados; se persistir, fallback pra prosa-template deterministica
(_template_prose) — NUNCA persiste prosa com vazamento. O lint so pega JARGAO,
nao coerencia; a coerencia vem do risco-fixo + spot-check humano/LLM-judge.

Espelha agent.classify_merito_synthesis (mesmo provider/temp0/thinking0), mas
prompt menor (sem matriz de decisao) -> mais barato e rapido.
"""

import json
import logging
import os
import re
from typing import Optional

from ...providers import create_provider
from ...providers.base import LLMResponse
from ...utils.llm_json import parse_llm_json
from .._utils import MODEL_VARIANT_TEXT
from . import prose_lint
from .prompts import REDACAO_PROMPT_VERSION, build_redacao_prompt
from .schemas import RedacaoCard, RedacaoRequest

logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.getenv("MERITO_SYNTHESIS_MODEL", "gemini-3.1-flash-lite")
DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER", "gemini")

_PROSE_FIELDS = (
    "justificativa", "narrativa_executiva", "contribuicao_no_risco",
    "decisao_justificativa_breve", "peca_pivo_motivo",
)

_RISCO_LC = {"Baixo": "baixo", "Medio": "medio", "Alto": "alto", "Altissimo": "altissimo"}


# ── Guard helpers ──────────────────────────────────────────────────────────


def _lint_card(card: dict) -> list[tuple[str, str]]:
    """Lint every prose field of the card (incl. proximos_passos joined)."""
    texts = [card.get(f) for f in _PROSE_FIELDS]
    texts.append(" ".join(card.get("proximos_passos_provaveis") or []))
    return prose_lint.lint_fields(*texts)


def _corrective_block(viols: list[tuple[str, str]]) -> str:
    """Retry hint ecoando os trechos vazados (recency anchor, last in prompt)."""
    trechos = sorted({v for _, v in viols})[:20]
    return (
        "<correcao_obrigatoria>\n"
        "Sua resposta anterior VAZOU jargao interno PROIBIDO pela Lista B (estes\n"
        "trechos): " + "; ".join(repr(t) for t in trechos) + ".\n"
        "REESCREVA todos os campos de prosa SEM esses termos, traduzindo-os pra\n"
        "portugues juridico corrente conforme o <filtro_redacao_advogado>. Esta e\n"
        "a regra mais importante: zero termos da Lista B.\n"
        "</correcao_obrigatoria>"
    )


# ── Deterministic template fallback (guaranteed List-B-clean) ──────────────
# Porta write29.det_justif/PROX — narra a decisao vigente e conclui com o
# risco_final em palavras. Espelha eval_29.facts2cell pra escolher a decisao
# dominante (a de pior banda) entre os processos.

_ORD = {"Baixo": 0, "Medio": 1, "Alto": 2, "Altissimo": 3}
_INST = {"1g": "em primeira instancia", "2g": "em segunda instancia",
         "stj": "no STJ", "stf": "no STF"}

_PROX = {
    "Baixo": ["Manter o monitoramento periodico do processo; nao ha acao imediata necessaria."],
    "Medio": ["Acompanhar a evolucao recursal e reavaliar o risco a medida que houver decisao de merito."],
    "Alto": ["Acompanhar de perto a tramitacao e avaliar a necessidade de reforco da garantia diante da decisao adversa."],
    "Altissimo": ["Risco iminente de acionamento da garantia; priorizar provisao e o acompanhamento do cumprimento/execucao."],
}


def _facts2cell(dv: dict) -> str:
    """eval_29.facts2cell (verbatim ordering) sobre 1 decisao_vigente dict."""
    nat = dv.get("natureza"); sent = dv.get("sentido"); inst = dv.get("instancia")
    transit = bool(dv.get("transito_certificado")); recorrida = bool(dv.get("recorrida"))
    if transit:
        if sent == "desfavoravel":
            return "Altissimo"
        if sent == "favoravel":
            return "Baixo"
        return "Medio" if sent == "parcial" else "Baixo"
    if nat in ("extinto_sem_merito", "interlocutoria", "homologatoria", None):
        return "Baixo"
    if sent == "favoravel":
        return "Baixo"
    if sent == "parcial":
        return "Medio"
    if sent == "desfavoravel":
        if inst in ("2g", "stj", "stf"):
            return "Alto"
        return "Medio" if recorrida else "Alto"
    return "Baixo"


def _dominant_decisao(req: RedacaoRequest) -> tuple[Optional[dict], Optional[str]]:
    """Pick the most decisive (worst-band) decisao_vigente + its processo CNJ."""
    best, best_pn, best_band = None, None, -1
    for ps in req.processo_syntheses or []:
        dv = ps.decisao_vigente or {}
        band = _ORD[_facts2cell(dv)]
        if band > best_band:
            best, best_pn, best_band = dv, ps.processo_numero, band
    return best, best_pn


def _template_prose(req: RedacaoRequest) -> dict:
    """Prosa-template deterministica (fallback). Narra a decisao vigente
    dominante e conclui com req.risco_final em palavras. List-B-clean por
    construcao (passa prose_lint sempre)."""
    risco = req.risco_final
    risco_lc = _RISCO_LC.get(risco, risco.lower())
    dv, pn = _dominant_decisao(req)
    dv = dv or {}
    sent = dv.get("sentido"); nat = dv.get("natureza")
    inst = _INST.get(dv.get("instancia"), "")
    transit = bool(dv.get("transito_certificado")); recorrida = bool(dv.get("recorrida"))
    cnj = f" (processo {pn})" if pn else ""

    if transit and sent == "desfavoravel":
        decisao = f"A decisao de merito foi desfavoravel ao tomador {inst}, ja transitada em julgado e sem recurso pendente{cnj}."
    elif transit and sent == "favoravel":
        decisao = f"A decisao de merito foi favoravel ao tomador {inst} e ja transitou em julgado{cnj}."
    elif nat in ("extinto_sem_merito", "interlocutoria", "homologatoria", None) and not transit:
        decisao = f"Nao ha decisao de merito desfavoravel vigente {inst}; o estagio atual do processo nao caracteriza perda para o tomador{cnj}."
    elif sent == "favoravel":
        decisao = f"A decisao vigente e favoravel ao tomador {inst}, ainda sem transito em julgado{cnj}."
    elif sent == "parcial":
        decisao = f"Houve procedencia parcial {inst}, ainda sem transito em julgado{cnj}."
    elif sent == "desfavoravel" and recorrida:
        decisao = f"Houve sentenca de merito desfavoravel ao tomador {inst}, com recurso pendente de julgamento{cnj}."
    elif sent == "desfavoravel":
        decisao = f"Houve decisao de merito desfavoravel ao tomador {inst}, sem recurso pendente no momento{cnj}."
    else:
        decisao = f"O estagio atual do processo {inst} foi avaliado para a definicao do risco{cnj}."
    decisao = re.sub(r"\s+", " ", decisao).strip()

    justificativa = f"{decisao} Considerados os elementos do caso, o risco de acionamento da garantia e {risco_lc}."
    return {
        "justificativa": justificativa,
        "narrativa_executiva": f"{decisao} Risco {risco}.",
        "contribuicao_no_risco": f"A perspectiva de exito das teses, no estagio atual, sustenta um risco {risco_lc} de acionamento da apolice.",
        "decisao_justificativa_breve": decisao,
        "peca_pivo_motivo": "",
        "proximos_passos_provaveis": list(_PROX.get(risco, [])),
    }


_MAIN_PROSE = ("justificativa", "narrativa_executiva", "contribuicao_no_risco",
               "decisao_justificativa_breve")


def _ensure_complete(card: dict, req: RedacaoRequest) -> dict:
    """Toda prosa OWNED com valor definido. Os 4 campos-texto principais + proximos
    NUNCA ficam vazios (preenche do template, que e List-B-clean e coerente com
    risco_final). peca_pivo_motivo pode ser '' (sem peca clara) — normaliza None->''.

    Por que: o passe so dispara quando o risco DIVERGIU; a prosa L3 existente foi
    escrita pro risco ANTIGO. Se um campo voltasse vazio, o materializer cairia na
    prosa stale (incoerente com o risco final). Definir tudo aqui fecha esse buraco.
    """
    tpl = None
    for f in _MAIN_PROSE:
        if not (card.get(f) or "").strip():
            tpl = tpl or _template_prose(req)
            card[f] = tpl[f]
    if not card.get("proximos_passos_provaveis"):
        tpl = tpl or _template_prose(req)
        card["proximos_passos_provaveis"] = tpl["proximos_passos_provaveis"]
    card["peca_pivo_motivo"] = card.get("peca_pivo_motivo") or ""
    return card


# ── Main entry ─────────────────────────────────────────────────────────────


async def _call_llm(provider, prompt: str, model: str) -> tuple[Optional[dict], str, dict]:
    """1 LLM call -> (parsed_card_dict | None, raw_text, usage)."""
    response: LLMResponse = await provider.agenerate(
        prompt=prompt,
        model=model,
        temperature=0.0,
        response_schema=RedacaoCard,
        thinking_budget=0,
        max_tokens=8192,  # so prosa, nunca infla como o L3 gigante
    )
    raw = response.text
    usage = {
        "input_tokens": response.input_tokens or 0,
        "output_tokens": response.output_tokens or 0,
        "cost_usd": (response.metadata.get("cost_usd", 0.0) if response.metadata else 0.0),
    }
    try:
        parsed = parse_llm_json(raw)
        card = RedacaoCard(**parsed).model_dump()
    except (json.JSONDecodeError, Exception) as e:  # noqa: BLE001
        logger.warning("REDACAO_PARSE_FAIL: %r | head=%r", e, raw[:200])
        card = None
    return card, raw, usage


async def redact_merito_synthesis(
    request: RedacaoRequest | dict,
    model: Optional[str] = None,
    provider: str = DEFAULT_PROVIDER,
) -> dict:
    """Verbaliza a prosa do merito pro risco JA decidido (request.risco_final).

    Guard: prose_lint -> 1 retry ecoando vazamentos -> fallback template.
    Returns {card, raw_response, llm_raw_prompt, prompt_version, usage,
             prose_source, prose_leak_cats}.
    """
    if isinstance(request, dict):
        request = RedacaoRequest(**request)
    model = model or request.model or DEFAULT_MODEL
    llm_provider = create_provider(provider)
    prompt = build_redacao_prompt(request)

    in_tok = out_tok = 0
    cost = 0.0
    leak_cats: list[str] = []
    raw_response = ""

    # Attempt 1.
    card, raw_response, u = await _call_llm(llm_provider, prompt, model)
    in_tok += u["input_tokens"]; out_tok += u["output_tokens"]; cost += u["cost_usd"]

    prose_source = "llm"
    # parse_fail e jargao-leak sao causas DISTINTAS de fallback — leak_cats so carrega
    # categorias REAIS do prose_lint (parse_fail polui a telemetria de vazamento).
    parse_failed = card is None
    viols = _lint_card(card) if card is not None else []

    if parse_failed or viols:
        if viols:
            leak_cats = sorted({c for c, _ in viols})
            logger.info(
                "L3_PROSE_LEAK merito_id=%s risco=%s cats=%s n=%d",
                request.merito_id, request.risco_final, ",".join(leak_cats), len(viols),
            )
        # Retry SO num card parseavel-mas-vazado (echoar leaks nao conserta parse-fail).
        retry_card = None
        if viols:
            retry_prompt = prompt + "\n\n" + _corrective_block(viols)
            retry_card, raw2, u2 = await _call_llm(llm_provider, retry_prompt, model)
            in_tok += u2["input_tokens"]; out_tok += u2["output_tokens"]; cost += u2["cost_usd"]
            if raw2:
                raw_response = raw2
        if retry_card is not None and not _lint_card(retry_card):
            card, prose_source = retry_card, "llm_retry"
        else:
            card, prose_source = _template_prose(request), "template"
            logger.info(
                "L3_PROSE_TEMPLATE_FALLBACK merito_id=%s risco=%s cause=%s",
                request.merito_id, request.risco_final,
                "parse_fail" if parse_failed else "leak_persisted",
            )

    # Garante que TODO campo de prosa owned tem valor definido (template preenche
    # vazios do LLM) — pro materializer sobrescrever sem deixar prosa STALE do risco
    # antigo sobreviver (finding review: campo vazio -> fallback stale).
    card = _ensure_complete(card, request)

    usage = {
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "total_tokens": in_tok + out_tok,
        "cost_usd": cost,
        "model": model,
        "provider": provider,
        "model_variant": MODEL_VARIANT_TEXT,
    }
    return {
        "card": card,
        "raw_response": raw_response,
        "llm_raw_prompt": prompt,
        "prompt_version": REDACAO_PROMPT_VERSION,
        "usage": usage,
        "prose_source": prose_source,
        "prose_leak_cats": leak_cats,
    }


__all__ = ["redact_merito_synthesis", "build_redacao_prompt", "RedacaoRequest", "RedacaoCard"]

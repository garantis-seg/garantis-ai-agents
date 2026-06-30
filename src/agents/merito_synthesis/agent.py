"""Merito Synthesis Agent - engine v6_meritos camada 3 (OUTPUT PRIMARIO).

Single LLM call por MERITO. Recebe processo_syntheses de TODOS processos do
merito + tomador + cda/aiim + snapshot anterior. Output:
risco + justificativa + trajetoria + peca_pivo + proximos_passos.
(Jurisprudencia saiu do payload na v2.2 — vive no L2, regras J/J.1/J.2.)

Persiste em monitoramento.risk_snapshots (orchestrator no frontend-api).
"""

import json
import logging
import os
from typing import Optional

from ...providers import create_provider
from ...providers.base import LLMResponse
from ...utils.llm_json import parse_llm_json
from .._utils import MODEL_VARIANT_TEXT, seed_for
from .prompts import build_prompt_and_version
from .schemas import MeritoSynthesisCard, MeritoSynthesisCardOut, MeritoSynthesisRequest

logger = logging.getLogger(__name__)

# extracao-sinais-merito-level (2026-06-29): fatos merito-level copiados do decisao_vigente
# do processo GOVERNANTE pro decisao_atual do card. Os 3 primeiros sao echo do L2
# DecisaoVigenteRich; os 3 ultimos sao o sinal #2 (suspensao deterministica da timeline).
_MERITO_ECHO_FIELDS = (
    "motivo_extincao", "instrumento_cautelar", "efeito_suspensivo",
    "suspensao_processual", "suspensao_vigente", "suspensao_data",
)


def _norm_pn(s) -> str:
    """Digits-only de um CNJ (formatado OU normalizado) — pra casar processo_de_origem
    com processo_synthesis.processo_numero independente de formatacao."""
    return "".join(ch for ch in str(s or "") if ch.isdigit())


def _project_merito_decisao_facts(card, processo_syntheses) -> None:
    """Copia os fatos merito-level (3 echo L2 + 3 suspensao) do decisao_vigente do processo
    GOVERNANTE (decisao_atual.processo_de_origem) pro decisao_atual do card. Sem isso o
    merito read-model era 0/244 nos 3 echo (o sinal morria na borda L2->L3). NUNCA levanta
    (best-effort — projecao nao pode derrubar a cascade)."""
    try:
        if not isinstance(card, dict) or "error" in card:
            return
        da = card.get("decisao_atual")
        if not isinstance(da, dict):
            return
        origem = _norm_pn(da.get("processo_de_origem"))
        if not origem:
            return
        match = None
        for ps in processo_syntheses or []:
            pn = ps.get("processo_numero") if isinstance(ps, dict) else getattr(ps, "processo_numero", None)
            if _norm_pn(pn) == origem:
                match = ps
                break
        if match is None:
            return
        dv = match.get("decisao_vigente") if isinstance(match, dict) else getattr(match, "decisao_vigente", None)
        if not isinstance(dv, dict):
            return
        for f in _MERITO_ECHO_FIELDS:
            if dv.get(f) is not None:
                da[f] = dv.get(f)
        card["decisao_atual"] = da
    except Exception as e:  # noqa: BLE001 — projecao e best-effort
        logger.warning("L3_PROJECT_MERITO_FACTS_FAIL: %r", e)

# 2026-06-28: default 2.5-flash -> 3.1-flash-lite, alinhado ao L2 (decisao Elton).
# NOTA: o L3 NAO foi observado pendurando (so o L2 tinha o hang do 2.5-flash) — mover
# o L3 e alinhamento, nao fix; como e a sintese FINAL (qualidade), o lite aqui e o que
# mais preocupa. Alvo real = 3.1-flash NAO-lite quando a quota GCP existir. Override via env.
# 2026-06-28 (shared 1.232.0): o ENGINE agora manda `model` no payload (SSOT;
# ENGINE_LAYER3_MODEL no worker) -> este default so vale como FALLBACK pra callers
# nao-engine. O caller do engine sobrescreve via request.model.
DEFAULT_MODEL = os.getenv("MERITO_SYNTHESIS_MODEL", "gemini-3.1-flash-lite")
DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER", "gemini")


def _assemble_ciclo_garantia(processo_syntheses) -> list[dict]:
    """Monta o ciclo_garantia (timeline cross-processo da garantia) DETERMINISTICAMENTE
    dos lifecycle_garantia dos processos — em vez de pedir pro LLM re-listar, o que
    fazia o L3 loopar numa lista runaway (680046: ~880 eventos / 145KB malformado →
    indeterminado). Ordena por data + dedupa. Shape = CicloGarantiaEvent (schemas.py)."""
    def _g(ps, k):
        return ps.get(k) if isinstance(ps, dict) else getattr(ps, k, None)

    events: list[dict] = []
    for ps in processo_syntheses or []:
        pn = _g(ps, "processo_numero")
        for ev in (_g(ps, "lifecycle_garantia") or []):
            if not isinstance(ev, dict):
                continue
            events.append({
                "data": ev.get("data"),
                "processo_numero": pn,
                "evento": ev.get("evento"),
                "tipo_garantia": ev.get("tipo_garantia"),
                "status_pos": ev.get("status_pos"),
                "motivo_recusa": ev.get("motivo_recusa"),
            })
    events.sort(key=lambda e: e.get("data") or "9999-99-99")
    seen: set = set()
    out: list[dict] = []
    for e in events:
        key = (e["data"], e["processo_numero"], e["evento"], e["status_pos"])
        if key not in seen:
            seen.add(key)
            out.append(e)
    return out


async def classify_merito_synthesis(
    request: MeritoSynthesisRequest | dict,
    model: Optional[str] = None,
    provider: str = DEFAULT_PROVIDER,
    bucket: Optional[str] = None,
) -> dict:
    """Synthesize a merito from its processo_syntheses + context cards.

    PR6 Architecture D: `bucket` opcional dispatcha variant prompt L3
    (factual_only / juris_only / mixed / derived_only). None = legacy
    single-prompt — comportamento idêntico ao pré-PR6.

    Returns:
        {"card": MeritoSynthesisCard.model_dump() | error_dict,
         "raw_response": str,
         "llm_raw_prompt": str,
         "usage": dict,
         "bucket": str | None}
    """
    if isinstance(request, dict):
        request = MeritoSynthesisRequest(**request)

    if model is None:
        model = DEFAULT_MODEL

    llm_provider = create_provider(provider)
    prompt, prompt_version = build_prompt_and_version(request, bucket=bucket)

    # v2.1: response_schema=MeritoSynthesisCard reativado depois que schema
    # foi reformatado pra eliminar dict[str, Any] (causa do additionalProperties
    # bug que tinha levado o response_schema a ser dropado). BreakdownProcesso
    # + CardsIndexCount substituem os dict legacy. Optional[str] enum
    # apertados pra Literal[...] strict pra evitar loop infinito decoder Gemini
    # (lição L2 v2.1).
    # Determinismo Bug 4 handoff: temperature=0.0 + thinking_budget=0 em
    # gemini-2.5-*. Provider aplica top_p=1.0, top_k=1 quando temp=0.
    # + seed determinístico (mérito + prompt): fecha o ~2% de micro-ruído residual
    # do L3 a temp=0 → mesmo input, mesma banda N×. Gated (ENGINE_LLM_SEED_ENABLED).
    seed = seed_for("merito_synthesis", request.merito_id, bucket, prompt)
    response: LLMResponse = await llm_provider.agenerate(
        prompt=prompt,
        model=model,
        temperature=0.0,
        response_schema=MeritoSynthesisCard,
        thinking_budget=0,
        seed=seed,
        # max_tokens 16384(default)->65536 (teto Gemini 2.5), 2026-06-17: meritos
        # GIGANTES (ex Petrobras 680195, 25 processos) geravam >16k tokens de output
        # -> JSON truncado -> JSONDecodeError -> retryable_500 5x -> indeterminado.
        # 65536 cabe folgado (so paga o output REAL gerado, nao o limite). Raiz, sem
        # fallback. (edital_summarizer tem retry-aware p/ casos >65536 — YAGNI aqui.)
        max_tokens=65536,
    )

    raw_response = response.text
    try:
        parsed = parse_llm_json(raw_response)
        # Echo IDs in case LLM dropped them
        parsed.setdefault("merito_id", request.merito_id)
        parsed.setdefault("merito_context", request.merito_context)
        # Default cards_index aggregation if LLM didn't fill
        # (campo `jurisprudencia` removido do request na v2.2 — referencia-lo
        # aqui levantava AttributeError engolido pelo except amplo abaixo,
        # convertendo card LLM VALIDO em parse-error sempre que cards_index
        # vinha vazio. CardsIndexCount.jurisprudencia default=0 cobre.)
        if not parsed.get("cards_index"):
            parsed["cards_index"] = {
                "processo_synthesis": len(request.processo_syntheses or []),
                "cda": len(request.cdas or []),
                "aiim": len(request.aiims or []),
                "tomador": 1 if request.tomador else 0,
            }
        card = MeritoSynthesisCardOut(**parsed)  # subclasse COM ciclo_garantia (response_model
        card_data = card.model_dump()            # tipa card por ela; response_schema do LLM
        #                                          fica MeritoSynthesisCard base, SEM ciclo)
        # ciclo_garantia montado em CÓDIGO (não pelo LLM — ver schemas.py): o LLM
        # loopava re-listando os eventos. Determinístico dos lifecycle_garantia do input.
        card_data["ciclo_garantia"] = _assemble_ciclo_garantia(request.processo_syntheses)
        # Projeta os fatos merito-level (echo L2 + suspensao) do processo governante pro
        # decisao_atual — determinístico, pós-LLM (mesma mecânica do ciclo_garantia). Fecha
        # o "satisfacao=0/86": sem isso o merito read-model perdia os sinais na borda L2->L3.
        _project_merito_decisao_facts(card_data, request.processo_syntheses)
        logger.info(
            "ciclo_garantia assembled merito_id=%s n_eventos=%d lifecycle_lens=%s",
            request.merito_id, len(card_data["ciclo_garantia"]),
            [len(getattr(p, "lifecycle_garantia", None) or []) for p in (request.processo_syntheses or [])],
        )
    except (json.JSONDecodeError, Exception) as e:
        # Diag (2026-06-19): L3 de mérito gigante gera JSON malformado/truncado.
        # raw_len + head/tail revelam o tamanho real + se trunca no max_tokens (corte
        # mid-JSON no tail) + qual campo infla. Remover quando o bloat do L3 for fechado.
        logger.error(
            f"merito_synthesis parse failed merito_id={request.merito_id}: {repr(e)} "
            f"| raw_len={len(raw_response)} head={raw_response[:220]!r} "
            f"tail={raw_response[-220:]!r}"
        )
        card_data = {
            "error": repr(e), "raw": raw_response,
            "merito_id": request.merito_id, "merito_context": request.merito_context,
        }

    usage = {
        "input_tokens": response.input_tokens or 0,
        "output_tokens": response.output_tokens or 0,
        "total_tokens": (response.input_tokens or 0) + (response.output_tokens or 0),
        "cost_usd": (response.metadata.get("cost_usd", 0.0) if response.metadata else 0.0),
        "model": model,
        "provider": provider,
        # L3 sempre text — não tem Vision path (consume cards L1/L2, não docs raw).
        "model_variant": MODEL_VARIANT_TEXT,
    }

    return {
        "card": card_data,
        "raw_response": raw_response,
        "llm_raw_prompt": prompt,
        "prompt_version": prompt_version,
        "usage": usage,
        "bucket": bucket,
    }

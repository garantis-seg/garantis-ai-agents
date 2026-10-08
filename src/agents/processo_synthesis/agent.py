"""Processo Synthesis Agent - engine v6_meritos camada 2.

Faz 1 LLM call: a synthesis (estado_processual, decisao_vigente, etc.). O card sai com
`probabilidade_exito` VAZIO, que o L3 trata como sem-sinal e decide pela Matriz de Risco.
⛔ Uma 2a call por processo multiplica o gasto da cascade (guarda: tests/test_l2_uma_call.py).
"""

import json
import logging
import os
import pathlib
from typing import Optional

from .._utils.prompt_identity import versao_com_identidade

from garantis_shared.llm_chunking import map_reduce_classify
from garantis_shared.llm_models import model_for

from ...providers import create_provider
from ...providers.base import LLMResponse
from ...utils.llm_json import parse_llm_json
from .._utils import MODEL_VARIANT_TEXT, seed_for
from .chunking import reduce_processo_synthesis_cards, split_movs_chronological
from .prompts import build_processo_synthesis_prompt
from .schemas import (
    DecisaoVigenteRich,
    ProbabilidadeExito,
    ProcessoSynthesisCard,
    ProcessoSynthesisRequest,
)

logger = logging.getLogger(__name__)

# ⛔ Nao volte pro 2.5-flash: ele PENDURA deterministico em certos prompts de L2 (request
# no vazio 0-token ate o teto; provado em isolamento, NAO e load/conexao/tamanho). O 3.1
# (mesmo do L1) nao tem o bug. CAVEAT: o lite e mais VOLATIL na sintese (extremos, alguns
# under-ratings Alto->Baixo) — o alvo de qualidade e o 3.1-flash NAO-lite, que hoje da 404
# no Vertex. Decisao do Elton: manter o lite ate o NAO-lite estar disponivel.
# O ENGINE manda `model` no payload (SSOT: ENGINE_LAYER2_MODEL no garantis-shared) -> este
# default so vale como FALLBACK pra callers nao-engine (curl/eval).
DEFAULT_MODEL = model_for("engine_layer2")
DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER", "gemini")

# ⭐ DERIVADA, nao mantida a mao. O rotulo `v2.5` continua legivel; o sufixo e
# `sha256[:12]` de (prompt + schema) — o que de fato molda a saida do LLM — e vai em
# telemetria.engine_llm_calls.prompt_version. Razao, medicoes e a armadilha do
# `summary_prompt_version`: `_utils/prompt_identity.py`.
PROMPT_VERSION = versao_com_identidade(
    "processo_synthesis.v2.5",
    str(pathlib.Path(__file__).with_name("prompts.py")),
    str(pathlib.Path(__file__).with_name("schemas.py")),
)


async def classify_processo_synthesis(
    request: ProcessoSynthesisRequest | dict,
    model: Optional[str] = None,
    provider: str = DEFAULT_PROVIDER,
    _no_chunk: bool = False,
) -> dict:
    """Synthesize a processo (1 LLM call).

    Processo GIGANTE (render dos movs > L2_CHUNK_CHARS) entra no chunk gate: split em
    lotes cronológicos → map-reduce paralelo (cada lote re-entra com _no_chunk=True). O
    caso normal (split=None) é byte-idêntico ao path histórico.

    Returns:
        {"card": ProcessoSynthesisCard.model_dump() | error_dict,
         "raw_response": {"synthesis": ...},
         "llm_raw_prompt": {"synthesis": str},
         "usage": dict}
    """
    if isinstance(request, dict):
        request = ProcessoSynthesisRequest(**request)
    if model is None:
        model = DEFAULT_MODEL

    # CHUNK GATE: processo GIGANTE (render dos movs > L2_CHUNK_CHARS) vira 1 prompt único
    # lento demais → estoura o TIMEOUT_LAYER2_S do worker → retry/loop. Split em lotes
    # CRONOLÓGICOS → classifica cada lote em PARALELO (_no_chunk=True → caminho normal, 1
    # call sobre <= _L2_BATCH_MAX_MOVS movs, prompt pequeno/rápido) → reduce por campo.
    # Lê COMPLETO sem timeout. Roda DENTRO do 1 HTTP do worker (o worker vê 1 resposta → step DBOS é 1 só →
    # replay-safe). Processo normal: split retorna None → caminho quente byte-idêntico.
    if not _no_chunk:
        variants = split_movs_chronological(request)
        if variants:
            result = await map_reduce_classify(
                variants=variants,
                classify_one=lambda v: classify_processo_synthesis(
                    v, model, provider, _no_chunk=True,
                ),
                reduce_cards=reduce_processo_synthesis_cards,
                label="l2_chunk",
            )
            # Lote(s) que falharam (parse/exception) são descartados pelo framework →
            # o reduce rodou sobre janela PARCIAL (pode ter perdido a janela load-bearing).
            # Torna VISÍVEL (não silent-swallow): log estruturado + clampa confianca pelo
            # ratio de sobrevivência. NÃO fail-closed (gigante tem que completar); o sinal
            # fica greppable + confianca rebaixada pro L3/auditoria. (Stricter: fail-closed.)
            n_ok, n_var = result.get("n_ok"), result.get("n_variants")
            card = result.get("card") or {}
            if (n_ok is not None and n_var and n_ok < n_var
                    and isinstance(card, dict) and "error" not in card):
                logger.warning(
                    "L2_CHUNK_PARTIAL pn=%s kept=%d total=%d — reduce sobre janela parcial; "
                    "confianca clampada",
                    request.processo_numero, n_ok, n_var,
                )
                if card.get("confianca") is not None:
                    card["confianca"] = round(card["confianca"] * n_ok / n_var, 3)
            # L2 tipa raw_response/llm_raw_prompt como dict {synthesis} (a route
            # ProcessoSynthesisResponse EXIGE dict). O framework devolve marker string →
            # embrulha pro shape do L2 (senão a serialização da response 500a).
            result["raw_response"] = {"synthesis": result.get("raw_response")}
            result["llm_raw_prompt"] = {"synthesis": result.get("llm_raw_prompt")}
            # Condicao A: projeta os fatos ECHO no card REDUZIDO usando os movs COMPLETOS
            # (request.mov_factsheets), nao os subsets dos chunks.
            _project_decisao_facts(result.get("card"), request.mov_factsheets)
            return result

    synthesis_result = await _call_synthesis(create_provider(provider), request, model, provider)

    card_data = _merge_results(request, synthesis_result)
    # Condicao A: projeta os fatos ECHO SO no outer call (nao nos sub-calls _no_chunk=True,
    # que veem subsets de movs). Proc normal: _no_chunk=False -> projeta com os movs completos.
    if not _no_chunk:
        _project_decisao_facts(card_data, request.mov_factsheets)

    return {
        "card": card_data,
        "raw_response": {"synthesis": synthesis_result["raw_response"]},
        "llm_raw_prompt": {"synthesis": synthesis_result["prompt"]},
        "prompt_version": PROMPT_VERSION,
        "usage": _usage_da_call(synthesis_result["usage"], model, provider),
    }


# ── Condicao A deterministica: projecao code-side dos fatos ECHO ─────────────
# ⛔ O LLM (response_schema = DecisaoVigente) NAO emite estes campos — faze-lo rebaixava
# o risco_factual (no canario; e o SCHEMA, nao so o prompt). Aqui copiamos do mov L1 que
# SUSTENTA a decisao vigente, SEM tocar a chamada do LLM. Quem os le e o L3.
_ECHO_FIELDS = ("motivo_extincao", "instrumento_cautelar", "efeito_suspensivo")

# ⛔ Por que NAO ha derivacao deterministica de transito aqui: uma correcao "novo merito
# apos transito -> transito=false" FOI construida e MEDIDA (A/B) e quebrou o trap da Acao
# Rescisoria — movs de FASE DE EXECUCAO (excecao de pre-executividade, embargos a
# execucao, impugnacao a liquidacao) carregam natureza procedente/improcedente IDENTICA a
# uma re-adjudicacao real, entao nenhum marcador L1 estruturado separa
# IRDR-de-merito de Acao-Rescisoria-de-execucao. A distincao vive em TEXTO LIVRE ->
# fica com o PROMPT (REGRA DE SUSPENSAO E TRANSITO) + com o L1 guard monotonico do L3
# (garantis-shared `engine_v6/matrices/risk_aggregation.py`, que so SOBE risco -> nao
# pode quebrar trap).


def _decisao_of(mov) -> dict:
    """decisao dict de um mov (MovFactSheetMin OU dict — o chunk passa objetos)."""
    d = getattr(mov, "decisao", None)
    if d is None and isinstance(mov, dict):
        d = mov.get("decisao")
    return d or {}


def _vigente_mov(mov_factsheets, natureza):
    """Mov L1 que sustenta a decisao_vigente (CRUX do matching): o mais recente com
    tem_decisao cuja natureza == a do card; fallback = o mais recente com tem_decisao.
    None quando nenhum mov tem decisao (card sem ancora -> nada a projetar)."""
    decided = [m for m in (mov_factsheets or []) if _decisao_of(m).get("tem_decisao")]
    if not decided:
        return None

    def _key(m):
        return (getattr(m, "data", None) or (m.get("data") if isinstance(m, dict) else "") or "",
                getattr(m, "mov_id", None) or (m.get("mov_id") if isinstance(m, dict) else "") or "")

    decided.sort(key=_key)
    if natureza:
        match = [m for m in decided if _decisao_of(m).get("natureza") == natureza]
        if match:
            return match[-1]
    return decided[-1]


def _project_decisao_facts(card, mov_factsheets) -> None:
    """Projeta os 3 fatos ECHO do mov L1 vigente pro decisao_vigente do card (dict),
    validando via DecisaoVigenteRich. No-op se card sem decisao_vigente/ancora. NUNCA
    levanta (best-effort — projecao nao pode derrubar a cascade)."""
    try:
        if not isinstance(card, dict) or "error" in card:
            return
        dv = card.get("decisao_vigente")
        if not isinstance(dv, dict):
            return
        mov = _vigente_mov(mov_factsheets, dv.get("natureza"))
        if mov is None:
            return
        d = _decisao_of(mov)
        enriched = {**dv, **{f: d.get(f) for f in _ECHO_FIELDS}}
        # Gate de precisao (sinal #1): motivo_extincao so e valido quando a decisao VIGENTE
        # do card e EXTINCAO. _vigente_mov faz fallback pro mov decidido mais recente
        # quando nenhum casa a natureza do card -> pode trazer o motivo de um mov de
        # extincao enquanto a decisao vigente e procedente/interlocutoria. So sobrevive
        # em extinto.
        if enriched.get("natureza") != "extinto_sem_merito":
            enriched["motivo_extincao"] = None
        card["decisao_vigente"] = DecisaoVigenteRich(**enriched).model_dump()
    except Exception as e:  # noqa: BLE001 — projecao e best-effort
        logger.warning("L2_PROJECT_FACTS_FAIL: %r", e)


async def _call_synthesis(llm_provider, request, model, provider) -> dict:
    """A call do L2.

    response_schema=ProcessoSynthesisCard (Gemini structured output nativo). O schema
    tem Optional[str] em campos enum (sentido/instancia/natureza) — descriptions ricas
    em Field guiam o LLM.

    Determinismo: temperature=0.0 + thinking_budget=0 (o provider aplica pra QUALQUER
    modelo). Provider aplica top_p=1.0, top_k=1 quando temp=0.
    """
    prompt = build_processo_synthesis_prompt(request)
    # seed determinístico (proc + prompt): re-síntese L2 reproduzível dado o input
    # — fecha a fonte que faz o risco oscilar sob resynthesize/L1-congelado. Gated
    # (ENGINE_LLM_SEED_ENABLED).
    seed = seed_for("processo_synthesis", request.processo_numero, prompt)
    response: LLMResponse = await llm_provider.agenerate(
        prompt=prompt, model=model, temperature=0.0,
        response_schema=ProcessoSynthesisCard,
        thinking_budget=0,
        seed=seed,
        # max_tokens acima do default (16384): processo com MUITOS movs gera card grande
        # demais -> JSON truncado -> 0 L2 cards. 65535 (nao 65536): limite da familia 2.5
        # no Vertex — 65536 da 400 INVALID_ARGUMENT (o GeminiProvider tambem clampa).
        max_tokens=65535,
    )
    return {"raw_response": response.text, "prompt": prompt, "usage": _usage_from(response)}


def _merge_results(request: ProcessoSynthesisRequest, synthesis_result: dict) -> dict:
    """Parse da synthesis num card final. Defensive: parse que falha => error_dict."""
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

        # ⛔ SEMPRE vazio, mesmo que o LLM o preencha: o campo esta no response_schema da call
        # (ProcessoSynthesisCard), e o prompt manda NAO inclui-lo. O L3 le classificacao=null
        # como sem-sinal.
        parsed["probabilidade_exito"] = ProbabilidadeExito().model_dump()

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


def _usage_from(response: LLMResponse) -> dict:
    return {
        "input_tokens": response.input_tokens or 0,
        "output_tokens": response.output_tokens or 0,
        "cached_tokens": getattr(response, "cached_tokens", 0) or 0,
        "cost_usd": (response.metadata.get("cost_usd", 0.0) if response.metadata else 0.0),
    }


def _usage_da_call(usage: dict, model: str, provider: str) -> dict:
    """O usage da call + model/provider. As chaves sao as de quando havia 2 calls (os
    consumidores leem `calls` e `total_tokens`)."""
    return {
        "input_tokens": usage["input_tokens"],
        "output_tokens": usage["output_tokens"],
        "total_tokens": usage["input_tokens"] + usage["output_tokens"],
        "cached_tokens": usage.get("cached_tokens", 0),
        "cost_usd": usage["cost_usd"],
        "model": model,
        "provider": provider,
        "calls": 1,
        # L2 sempre text — não tem Vision path (consume cards L1, não docs raw).
        "model_variant": MODEL_VARIANT_TEXT,
    }

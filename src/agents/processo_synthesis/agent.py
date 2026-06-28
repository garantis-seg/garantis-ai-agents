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

from garantis_shared.llm_chunking import map_reduce_classify

from ...providers import create_provider
from ...providers.base import LLMResponse
from ...utils.llm_json import parse_llm_json
from .._utils import MODEL_VARIANT_TEXT
from .chunking import reduce_processo_synthesis_cards, split_movs_chronological
from .prompts import build_probabilidade_exito_prompt, build_processo_synthesis_prompt
from .schemas import (
    DecisaoVigenteRich,
    ProbabilidadeExito,
    ProcessoSynthesisCard,
    ProcessoSynthesisRequest,
)

logger = logging.getLogger(__name__)

# 2026-06-28: default 2.5-flash -> 3.1-flash-lite. O 2.5-flash PENDURA deterministico
# em certos prompts de L2 (1 proc/merito, request no vazio 0-token ate o teto; isolation-
# provado, NAO load/conn/size — keepalive/concorrencia descartados). O 3.1 (mesmo do L1)
# nao tem o bug. CAVEAT: o lite e mais VOLATIL na sintese (validacao 29 vs Poletto:
# extremos, alguns under-ratings Alto->Baixo) — alvo de qualidade real e o 3.1-flash
# NAO-lite (sem quota GCP hoje). Decisao Elton: manter lite ate provisionar a quota.
# 2026-06-28 (shared 1.232.0): o ENGINE agora manda `model` no payload (SSOT;
# ENGINE_LAYER2_MODEL no worker) -> este default so vale como FALLBACK pra callers
# nao-engine (curl/eval). O caller do engine sobrescreve via request.model.
DEFAULT_MODEL = os.getenv("PROCESSO_SYNTHESIS_MODEL", "gemini-3.1-flash-lite")
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
#
# v2.3 (2026-06-12, SEM CAP de dados — decisao Elton, revisao L2/L3):
#   - _MAX_MOVS_INLINE=50 removido dos 2 builders (cortava a peticao 1P +
#     movs antigas; censo: p99=2026 movs cabe no contexto 1M). Guard
#     fail-loud L2_PROMPT_SIZE/OVERSIZE no lugar (nunca trunca).
#   - Truncagens de render removidas (resumo_ato/motivos/resumo_dia/eventos).
#   - Instrucoes mortas de "autos raw" removidas (ex-REGRA F; G ESTABILIDADE
#     TEMPORAL renumerada pra F).
#   - Instrucoes novas: leitura da PETICAO INICIAL (mov_id 'peticao-<pn>')
#     + split por documento ('<id>:<doc>').
#   - CAVEAT regra_polos atualizado pro sentido deterministico on-read (v4).
#   - Rollback: revert do PR (regen COLD na versao anterior).
#
# v2.4 (2026-06-28, L0 DADO — fix do over-claim de transito_certificado):
#   - PROMPT-ONLY: REGRA DE SUSPENSAO E TRANSITO (distincao MERITO-vs-EXECUCAO) +
#     suspensao tirada da lista de "mero impulso" + carve-out na REGRA F +
#     lembrete_final. Suspensao-de-merito (IRDR/Tema/sobrestamento/recurso
#     pendente)/anulacao/reativacao -> transito=false; suspensao-de-execucao-
#     pos-transito (Acao Rescisoria/RJ/parcelamento) -> mantem true.
#   - SEM derivacao deterministica de transito: foi construida + MEDIDA (A/B) e
#     quebra o trap Acao Rescisoria (movs de execucao tem natureza de merito) ->
#     a distincao e text-only, fica no prompt + L1 GUARD. Ver _project_decisao_facts.
#   - Bump invalida cache do L2 -> cards novos pegam o prompt; existentes limpam
#     no re-cascade (handoff prompt-DADO-fix-transito-L2). Memory:
#     l2-transito-overclaim-rootcause-2026-06-28.
PROMPT_VERSION = "processo_synthesis.v2.4"


async def classify_processo_synthesis(
    request: ProcessoSynthesisRequest | dict,
    model: Optional[str] = None,
    provider: str = DEFAULT_PROVIDER,
    _no_chunk: bool = False,
) -> dict:
    """Synthesize a processo + classify probabilidade_exito (2 LLM calls em paralelo).

    Processo GIGANTE (render dos movs > L2_CHUNK_CHARS) entra no chunk gate: split em
    lotes cronológicos → map-reduce paralelo (cada lote re-entra com _no_chunk=True). O
    caso normal (split=None) é byte-idêntico ao path histórico.

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

    # CHUNK GATE: processo GIGANTE (render dos movs > L2_CHUNK_CHARS) vira 1 prompt único de
    # 250s+ → estoura TIMEOUT_LAYER2_S=180s no worker → retry/loop. Split em lotes
    # CRONOLÓGICOS → classifica cada lote em PARALELO (_no_chunk=True → caminho normal de 2
    # calls sobre <=200 movs, prompt pequeno/rápido) → reduce por campo. Lê COMPLETO sem
    # timeout. Roda DENTRO do 1 HTTP do worker (o worker vê 1 resposta → step DBOS é 1 só →
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
            # §F4/F6: lote(s) que falharam (parse/exception) são descartados pelo framework →
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
            # L2 tipa raw_response/llm_raw_prompt como dict {synthesis, prob_exito} (a route
            # ProcessoSynthesisResponse EXIGE dict). O framework devolve marker string →
            # embrulha pro shape do L2 (senão a serialização da response 500a).
            marker_raw = result.get("raw_response")
            marker_prompt = result.get("llm_raw_prompt")
            result["raw_response"] = {"synthesis": marker_raw, "prob_exito": marker_raw}
            result["llm_raw_prompt"] = {"synthesis": marker_prompt, "prob_exito": marker_prompt}
            # Condicao A: projeta os fatos ECHO no card REDUZIDO usando os movs COMPLETOS
            # (request.mov_factsheets), nao os subsets dos chunks.
            _project_decisao_facts(result.get("card"), request.mov_factsheets)
            return result

    llm_provider = create_provider(provider)

    synthesis_task = _call_synthesis(llm_provider, request, model, provider)

    # §3.1 exito-gate (flag EXITO_GATED_ON_JURIS, default OFF). A probabilidade de
    # exito (Matriz Daycoval, call B) so agrega valor quando ha jurisprudencia REAL;
    # sem sinal de juris ela vira ~redundante com o risco_factual. Com a flag ON e
    # SEM sinal de juris, pulamos a call B -> card sai com probabilidade_exito vazio
    # (L3 trata classificacao=null como sem-sinal -> decide pela Matriz de Risco/
    # estagio). Default OFF = byte-identical ate flip + A/B: o engine ja bate Poletto
    # com exito-como-contexto (validado 2026-06-21), entao a mudanca espera medicao.
    # Ver memory l2-redesign-locked-2026-06-20 §3.1.
    n_calls = 2
    if _exito_gate_enabled() and not _juris_has_signal(request):
        synthesis_result = await synthesis_task
        prob_exito_result = {
            "raw_response": "{}",  # parseia pra ProbabilidadeExito() vazio -> sem-sinal
            "prompt": "(exito gated: sem sinal de jurisprudencia — call B pulada)",
            "usage": {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
        }
        n_calls = 1
        logger.info(
            "EXITO_GATED pn=%s (sem sinal juris) — call B pulada",
            request.processo_numero,
        )
    else:
        prob_exito_task = _call_probabilidade_exito(llm_provider, request, model, provider)
        # §F5: return_exceptions=True — uma call que LEVANTA (TPM timeout/503 sob a saturação
        # que o chunking enfrenta) não pode descartar o lote inteiro. synthesis é load-bearing
        # (re-raise como antes); call B que levanta degrada pra prob vazio (mesmo fallback do
        # exito-gate) preservando a synthesis boa — espelha a degradação graciosa do _parse_prob_exito.
        synthesis_result, prob_exito_result = await asyncio.gather(
            synthesis_task, prob_exito_task, return_exceptions=True,
        )
        if isinstance(synthesis_result, BaseException):
            raise synthesis_result
        if isinstance(prob_exito_result, BaseException):
            if not isinstance(prob_exito_result, Exception):
                raise prob_exito_result  # CancelledError etc — não engole
            logger.warning(
                "prob_exito RAISED pn=%s: %r — card sai com probabilidade_exito vazio",
                request.processo_numero, prob_exito_result,
            )
            prob_exito_result = {
                "raw_response": "{}",
                "prompt": "(prob_exito raised — degradado pra vazio)",
                "usage": {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
            }
            n_calls = 1

    card_data = _merge_results(request, synthesis_result, prob_exito_result)
    # Condicao A: projeta os fatos ECHO SO no outer call (nao nos sub-calls _no_chunk=True,
    # que veem subsets de movs). Proc normal: _no_chunk=False -> projeta com os movs completos.
    if not _no_chunk:
        _project_decisao_facts(card_data, request.mov_factsheets)
    usage = _merge_usage(
        synthesis_result["usage"], prob_exito_result["usage"], model, provider, calls=n_calls,
    )

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


# ── Condicao A deterministica (2026-06-25): projecao code-side dos fatos ECHO ──
# O LLM (response_schema = DecisaoVigente v2.3 INTOCADA) NAO emite estes campos —
# faze-lo rebaixava o risco_factual (canario: 6 quedas estaveis; e o SCHEMA, nao so o
# prompt). Aqui copiamos do mov L1 que SUSTENTA a decisao vigente, SEM tocar a chamada
# do LLM. Inerte ate o L3 ler. Memory: l2-propagar-fatos-canary-finding-2026-06-25.
_ECHO_FIELDS = ("motivo_extincao", "instrumento_cautelar", "efeito_suspensivo")

# Por que NAO ha derivacao deterministica de transito aqui (L0 DADO 2026-06-28):
# uma correcao "novo merito apos transito -> transito=false" FOI construida e MEDIDA
# (LLM A/B nos 23 cards transito=true) e quebrou o trap Acao Rescisoria 00107231 —
# movs de FASE DE EXECUCAO (excecao de pre-executividade, embargos a execucao,
# impugnacao a liquidacao) carregam natureza procedente/improcedente IDENTICA a uma
# re-adjudicacao real, entao nenhum marcador L1 estruturado separa
# IRDR-de-merito de Acao-Rescisoria-de-execucao. A distincao vive em TEXTO LIVRE ->
# fica com o PROMPT (REGRA DE SUSPENSAO E TRANSITO, v2.4) + com o L1 GUARD monotonico
# (proposta L1, que so SOBE risco -> nao pode quebrar trap). Memory:
# l2-transito-overclaim-rootcause-2026-06-28.


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
        card["decisao_vigente"] = DecisaoVigenteRich(**enriched).model_dump()
    except Exception as e:  # noqa: BLE001 — projecao e best-effort
        logger.warning("L2_PROJECT_FACTS_FAIL: %r", e)


def _exito_gate_enabled() -> bool:
    """§3.1: flag EXITO_GATED_ON_JURIS (default OFF). ON => pula a call B de
    probabilidade_exito quando NAO ha sinal de jurisprudencia (deixa a Matriz de
    Risco/estagio decidir). Default OFF preserva comportamento byte-identical."""
    return os.environ.get("EXITO_GATED_ON_JURIS", "").strip().lower() in ("1", "true", "yes", "on")


def _juris_has_signal(request: ProcessoSynthesisRequest) -> bool:
    """True se jurisprudencia_externa traz resultado DIRECIONAL (nao None/vazio/
    'indeterminado'). E o gate de exito do §3.1 — sem sinal direcional, a
    probabilidade_exito nao tem juris real pra agregar."""
    je = request.jurisprudencia_externa
    if je is None:
        return False
    return (je.resultado_majoritario or "").strip().lower() not in ("", "indeterminado")


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
        # max_tokens 16384(default)->65536 (2026-06-17): processos com MUITOS movs
        # (ex 680067, 393) geravam card grande demais -> JSON truncado -> 0 L2 cards.
        max_tokens=65536,
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
    usage_a: dict, usage_b: dict, model: str, provider: str, calls: int = 2,
) -> dict:
    """Soma os 2 calls + adiciona model/provider. `calls` reflete quantas LLM calls
    rodaram de fato (1 quando o exito-gate §3.1 pula a call B)."""
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
        "calls": calls,
        # L2 sempre text — não tem Vision path (consume cards L1, não docs raw).
        "model_variant": MODEL_VARIANT_TEXT,
    }

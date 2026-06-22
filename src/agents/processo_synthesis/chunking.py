# -*- coding: utf-8 -*-
"""Chunk map-reduce de processo GIGANTE no L2 (2026-06-22).

Processo com muito SINAL vira 1 prompt único que o Gemini leva 250s+ → estoura
TIMEOUT_LAYER2_S=180s no worker → retry → loop. O filtro de relevância (2026-06-20) já
encolhe os procedural-giants (dropa ruido/baixa → 84s); o chunking é o 2º eixo, pro caso
em que até o SINAL filtrado é grande demais: split em lotes CRONOLÓGICOS → classifica cada
lote em PARALELO (cada um < timeout) → reduz por semântica de campo.

⭐ COMPÕE com o filtro (fix 2026-06-22): detector + split operam sobre o conjunto FILTRADO
(`_filtered_cards`), NÃO sobre todos os movs. Chunkar os brutos relia os procedurais que o
filtro dropa = 6× mais trabalho → regrediu procedural-giants (680046 timeout vs 84s
filtrado). Agora processo procedural-giant não chunka (via filtrada); só chunka quando o
sinal filtrado passa de 120k. Ver split_movs_chronological.

Aqui só o split (por-layer) + reduce (por-layer), puros e testáveis. A orquestração
genérica (gather paralelo → filtra OK → reduce → soma usage) é
`garantis_shared.llm_chunking.map_reduce_classify`, chamada no agent.py. ESPELHA o
padrão do L1 (mov_factsheet/chunking.py).

Aqui só o split (por-layer) + reduce (por-layer), puros e testáveis. A orquestração
genérica (gather paralelo → filtra OK → reduce → soma usage) é
`garantis_shared.llm_chunking.map_reduce_classify`, chamada no agent.py. ESPELHA o
padrão do L1 (mov_factsheet/chunking.py).

Reduce — semântica por campo (ANCHOR no lote da decisão que governa; review 2026-06-22):
  decisao_vigente : HIERARQUIA load-bearing (transito > instância > mérito > recência) —
                    define o ANCHOR. NÃO é "último lote" cego. transito/recorrida OR-merged
                    de todas as janelas (a certidão de trânsito cai num lote sem a sentença).
  risco_* / prob  : do ANCHOR (a decisão que governa) — coerentes entre si. NÃO MAX cego
                    (MAX super-flagava de-escalação real: acordo/extinção/garantia-aceita).
  lifecycle       : UNION dedup por (data, mov_id, evento), ordenado por data.
  valores         : MAX não-null por campo.
  estado/trajet.  : ÚLTIMO lote (janela mais recente = estado corrente).
  movs_processed  : SOMA (total real de movs lidos em todas as janelas).
  confianca       : MIN (janelas parciais → menos confiança).

Lote(s) que falham (parse/exception) são descartados pelo framework → o reduce roda sobre
janela PARCIAL. O agent.py torna isso VISÍVEL (log L2_CHUNK_PARTIAL + clamp de confianca via
n_ok/n_variants), nunca silencioso.

ponytail: SEM marcador "[PARTE j/N]" no prompt do lote (de propósito) — adicioná-lo mudaria
o template e forçaria bump de PROMPT_VERSION = re-cascade de TODOS os procs, não só os ~22
gigantes. O reduce faz o raciocínio cross-janela; o LLM só sintetiza cada janela.
"""
from __future__ import annotations

import os
from typing import Optional

from .prompts import _filtered_cards, _summarize_factsheet
from .schemas import ProcessoSynthesisRequest

# DOIS thresholds distintos (fix 2026-06-22 — antes era 1 só, e baixo demais):
#
# DETECTOR (quando chunkar): o render FILTRADO precisa passar disto. Medido: o 680046
# (pior gigante monit, ~530k de timeline filtrada) roda como CHAMADA ÚNICA em ~84s — bem
# sob os 180s. Ou seja, a via filtrada única aguenta os gigantes conhecidos; chunkar eles
# só ADICIONA carga na instância (foi o que death-spiralou). Então só chunka quando o sinal
# filtrado é grande demais pro single call arriscar o timeout (~800k ≈ ~127s extrapolado).
# Na prática: dormente pros monit atuais (filtro resolve), rede de segurança pros monstros.
_L2_CHUNK_DETECT_CHARS = int(os.getenv("L2_CHUNK_DETECT_CHARS", "800000"))
# ORÇAMENTO POR LOTE (quando chunka): cada lote vira 1 prompt pequeno/rápido (~120k +
# scaffolding < ~200k = teto dos ~60s/call). env-configurável (handoff §6.3).
L2_CHUNK_CHARS = int(os.getenv("L2_CHUNK_CHARS", "120000"))

# Teto de movs por lote = o threshold do filtro de relevância (_render_timeline em
# prompts.py). Os lotes operam sobre o conjunto FILTRADO (já só sinal), e ficar <= esse
# teto garante que o filtro não RE-dispara dentro do lote. Cross-check: _L2_CARD_FILTER_THRESHOLD.
_L2_BATCH_MAX_MOVS = 200


def _est_render_chars(movs: list) -> int:
    """Estima o tamanho de render no prompt — a MESMA fn (_summarize_factsheet) do builder,
    pra o detector bater com o tamanho real do prompt (+4 = o '\\n  ' do join)."""
    return sum(len(_summarize_factsheet(f)) + 4 for f in movs)


def split_movs_chronological(
    req: ProcessoSynthesisRequest,
    detect_chars: Optional[int] = None,
    batch_chars: Optional[int] = None,
) -> Optional[list[ProcessoSynthesisRequest]]:
    """Divide os cards em lotes CRONOLÓGICOS quando o SINAL filtrado é grande demais.

    COMPÕE COM O FILTRO DE RELEVÂNCIA (fix 2026-06-22): detector e split operam sobre o
    conjunto FILTRADO (`_filtered_cards` — só sinal + cauda, o MESMO que a chamada única
    renderiza), NÃO sobre todos os movs. Chunkar os brutos relia milhares de procedurais que
    o filtro dropa = 6× mais trabalho → regrediu procedural-giants (680046: filtro fazia 84s;
    chunk-tudo dava timeout 180s).

    DOIS thresholds: `detect_chars` (quando chunkar — render filtrado precisa passar disto;
    default _L2_CHUNK_DETECT_CHARS alto → via filtrada única é preferida pros gigantes
    conhecidos) e `batch_chars` (tamanho de cada lote quando chunka; default L2_CHUNK_CHARS
    pequeno → lote rápido). Cada lote fecha ao atingir batch_chars OU _L2_BATCH_MAX_MOVS cards.
    None quando não precisa chunkar (caminho quente byte-idêntico).

    Determinismo: MESMA ordenação do build_processo_synthesis_prompt (data ASC, mov_id ASC)
    → lotes estáveis entre cascades → reduce determinístico (invariante de replay).
    """
    detect_chars = detect_chars or _L2_CHUNK_DETECT_CHARS
    batch_chars = batch_chars or L2_CHUNK_CHARS
    movs = req.mov_factsheets or []
    movs_sorted = sorted(movs, key=lambda f: (f.data or "", f.mov_id or ""))
    # Só o conteúdo FILTRADO é renderizado no prompt — é ele que o detector mede e o split fatia.
    kept, _ = _filtered_cards(movs_sorted)
    if _est_render_chars(kept) <= detect_chars:
        return None

    batches: list[list] = []
    cur: list = []
    cur_chars = 0
    for f in kept:
        sz = len(_summarize_factsheet(f)) + 4
        if cur and (cur_chars + sz > batch_chars or len(cur) >= _L2_BATCH_MAX_MOVS):
            batches.append(cur)
            cur, cur_chars = [], 0
        cur.append(f)
        cur_chars += sz
    if cur:
        batches.append(cur)
    if len(batches) < 2:
        # 1 card gigante sozinho estourou o orçamento — chunkar não ajuda (1 lote só).
        return None

    return [req.model_copy(update={"mov_factsheets": batch}) for batch in batches]


# ── reduce (semântica por campo) ───────────────────────────────────────────

_INST_RANK = {"stf": 4, "stj": 3, "2g": 2, "1g": 1}
_MERITO_NAT = {
    "procedente", "improcedente", "parcialmente_procedente",
    "extinto_sem_merito", "homologatoria",
}
_WEIGHT_RANK = {"high": 3, "medium": 2, "low": 1}


def _max_val(cards: list[dict], field: str):
    vals = [c.get(field) for c in cards if c.get(field) is not None]
    return max(vals) if vals else None


def _union_lifecycle(cards: list[dict]) -> list[dict]:
    seen, out = set(), []
    for c in cards:
        for ev in (c.get("lifecycle_garantia") or []):
            ev = ev or {}
            k = (ev.get("data"), ev.get("mov_id"), ev.get("evento"))
            if k in seen:
                continue
            seen.add(k)
            out.append(ev)
    out.sort(key=lambda ev: ((ev or {}).get("data") or "", str((ev or {}).get("mov_id") or "")))
    return out


def _merge_evidence(cards: list[dict]) -> list[dict]:
    seen, items = set(), []
    for c in cards:
        for e in (c.get("evidence_artifacts") or []):
            mid = (e or {}).get("mov_id")
            if mid and mid in seen:
                continue
            if mid:
                seen.add(mid)
            items.append(e)
    items.sort(key=lambda e: _WEIGHT_RANK.get((e or {}).get("weight"), 0), reverse=True)
    return items[:5]


def reduce_processo_synthesis_cards(cards: list[dict]) -> dict:
    """Combina N ProcessoSynthesisCard.model_dump() (lotes cronológicos) → 1 card.

    ANCHOR = lote cuja decisao_vigente é a mais load-bearing (hierarquia transito >
    instância > mérito > recência, mirror do dec_score do L1). Os campos derivados do
    ESTADO DECISÓRIO — decisao_vigente, risco_processo_intermediario, risco_factual,
    risco_jurisprudencial, probabilidade_exito — vêm DELE: coerentes entre si e com a
    decisão que governa. NÃO é MAX cego entre lotes (MAX super-flagava de-escalação REAL:
    acordo homologado / garantia aceita / extinção reduzem o risco — review 2026-06-22 §F1;
    e prob_exito vinha do tail procedural fraco em vez da janela com a decisão — §F2).
    estado_processual/trajetoria/peca_pivo vêm da janela mais RECENTE (estado corrente).
    transito_certificado/recorrida são OR-merged de TODAS as janelas: a certidão de trânsito
    costuma cair num lote SEM a sentença (natureza=null → fora do anchor), então o pick
    sozinho perderia o flag e sub-flagava o pior caso (§F3). lifecycle=union, valores=max,
    movs=soma, confianca=min. Identidade (processo_numero/classe/.../tipo_judicial) do 1º lote.
    Estilo espelha reduce_peca_cards do L1: picks 1-caller são closures locais.
    """
    assert cards, "reduce sem cards"

    def has_decision(c):
        d = c.get("decisao_vigente") or {}
        return d.get("natureza") is not None or d.get("sentido") is not None

    def dec_score(c):  # transito > instância > decisão de mérito (vs interlocutória) > recência
        d = c.get("decisao_vigente") or {}
        return (
            bool(d.get("transito_certificado")),
            _INST_RANK.get(d.get("instancia"), 0),
            d.get("natureza") in _MERITO_NAT,
            d.get("data") or "",
        )

    withdec = [c for c in cards if has_decision(c)]
    anchor = max(withdec, key=dec_score) if withdec else cards[-1]

    decisao = dict(anchor.get("decisao_vigente") or {})
    # §F3: trânsito/recurso certificado em QUALQUER janela vale pra decisão escolhida.
    if any((c.get("decisao_vigente") or {}).get("transito_certificado") for c in cards):
        decisao["transito_certificado"] = True
    if any((c.get("decisao_vigente") or {}).get("recorrida") for c in cards):
        decisao["recorrida"] = True

    # estado/peça-pivô: janela mais RECENTE (estado corrente)
    estado = next(
        (c["estado_processual"] for c in reversed(cards)
         if (c.get("estado_processual") or "").strip()),
        cards[-1].get("estado_processual") or "",
    )
    pivos = [c.get("peca_pivo_candidata") for c in cards
             if (c.get("peca_pivo_candidata") or {}).get("mov_id")]
    peca_pivo = (max(pivos, key=lambda p: (p or {}).get("data") or "")
                 if pivos else cards[-1].get("peca_pivo_candidata") or {})

    out = dict(cards[0])  # identidade + defaults; sobrescrevo os campos reduzidos abaixo
    out["estado_processual"] = estado
    out["decisao_vigente"] = decisao
    out["lifecycle_garantia"] = _union_lifecycle(cards)
    out["risco_processo_intermediario"] = anchor.get("risco_processo_intermediario") or "Baixo"
    out["risco_factual"] = anchor.get("risco_factual") or "Indeterminado"
    out["risco_jurisprudencial"] = anchor.get("risco_jurisprudencial") or "Indeterminado"
    out["trajetoria_dentro_processo"] = cards[-1].get("trajetoria_dentro_processo") or "indefinida"
    out["peca_pivo_candidata"] = peca_pivo
    out["valor_em_disputa"] = _max_val(cards, "valor_em_disputa")
    out["valor_garantia"] = _max_val(cards, "valor_garantia")
    out["probabilidade_exito"] = anchor.get("probabilidade_exito") or {}
    out["movs_processed"] = sum(int(c.get("movs_processed") or 0) for c in cards)
    out["confianca"] = min((c.get("confianca") or 0.7 for c in cards), default=0.7)
    out["evidence_artifacts"] = _merge_evidence(cards)
    return out

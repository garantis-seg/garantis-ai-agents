# -*- coding: utf-8 -*-
"""Chunk map-reduce de PEÇA grande no L1 (2026-06-19).

Peça (petição/sentença/acórdão...) > ~200k chars estoura o L1 (Gemini >60s →
TIMEOUT_LAYER1_S). Elton: peça = ler COMPLETO (não head+tail como evidência).
Solução: split em chunks de ~180k → classifica cada um em PARALELO → reduz por
semântica de campo. ~300 peças >500k no corpus (115 de 500-800k + 185 >800k).

Aqui só split + reduce (puros, testáveis). A orquestração (gather das N calls)
fica no agent.py — `_classify_chunked` recursa em classify_mov_factsheet com
_no_chunk=True (cada chunk <CHUNK_SIZE → 1 call normal), reduz os cards JÁ
construídos e RE-DERIVA (categoria/status/...) pra consistência.
"""
from __future__ import annotations

from .prompts_v4 import _doc_reading_profile
from .schemas import DocAnexado

CHUNK_SIZE = 180_000   # < 200k (margem pro marcador + mov + outros docs no prompt;
                       # 200k de prompt é o teto comprovado dos 60s)
_RESUMO_CAP = 3000
_REL = {"alta": 3, "media": 2, "baixa": 1, "ruido": 0}


def _split_text(text: str, size: int = CHUNK_SIZE) -> list[str]:
    """Pedaços <= size, quebrando em '\\n' quando há um na 2a metade (não corta linha)."""
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        end = min(i + size, n)
        if end < n:
            nl = text.rfind("\n", i + size // 2, end)
            if nl != -1:
                end = nl + 1
        out.append(text[i:end])
        i = end
    return out


def split_large_peca_variants(docs: list[DocAnexado]) -> list[list[DocAnexado]] | None:
    """Se há UMA peça > CHUNK_SIZE, devolve N variantes de docs (a peça trocada por
    cada chunk, com marcador de parte). None se nenhum chunk é necessário.

    ponytail: trata a MAIOR peça grande. 2+ peças gigantes no mesmo mov (raro) — as
    outras seguem inteiras na variante (podem ser lentas); upgrade: chunkar todas.
    """
    big_idx, big_len = None, CHUNK_SIZE
    for i, d in enumerate(docs):
        if len(d.text_content or "") > big_len and _doc_reading_profile(d) == "peca":
            big_idx, big_len = i, len(d.text_content or "")
    if big_idx is None:
        return None
    big = docs[big_idx]
    pieces = _split_text(big.text_content or "")
    n = len(pieces)
    if n <= 1:
        return None
    variants: list[list[DocAnexado]] = []
    for j, piece in enumerate(pieces):
        marked = f"[PARTE {j + 1}/{n} de documento dividido — leia como continuação]\n{piece}"
        chunk_doc = big.model_copy(update={"text_content": marked})
        variants.append([chunk_doc if k == big_idx else d for k, d in enumerate(docs)])
    return variants


def _union(cards: list[dict], field: str, key: str) -> list[dict]:
    """Union dedup por `key` (cdas por numero, processos_citados por cnj)."""
    seen, out = set(), []
    for c in cards:
        for item in (c.get(field) or []):
            k = (item or {}).get(key)
            if k and k not in seen:
                seen.add(k)
                out.append(item)
    return out


def reduce_peca_cards(cards: list[dict]) -> dict:
    """Combina N cards (built MovFactSheetCardV4 dicts) de chunks de UM doc → 1 card base.

    Semântica por campo:
      relevancia = max; tipo_doc = do chunk mais relevante (evita 'outros');
      decisao = chunk com sinal mais forte (transito > natureza > tem_decisao);
      evento_garantia = 1o chunk com evento != nenhum; valores = max não-null/campo;
      resumo = concat não-ruido (dedup); cdas/citados = union.
    Derivados (categoria/status/...) NÃO são reduzidos — re-derive no caller.
    """
    assert cards, "reduce sem cards"
    best_rel = max(cards, key=lambda c: _REL.get(c.get("relevancia_merito"), 0))

    def dec_score(c: dict):
        d = c.get("decisao") or {}
        return (bool(d.get("transito_certificado")), d.get("natureza") is not None, bool(d.get("tem_decisao")))

    best_dec = max(cards, key=dec_score)

    eg = next((c.get("evento_garantia") for c in cards
               if (c.get("evento_garantia") or {}).get("tipo", "nenhum") != "nenhum"), None)
    eg = eg or (cards[0].get("evento_garantia") or {"tipo": "nenhum"})

    def vmax(field: str):
        vals = [(c.get("valores") or {}).get(field) for c in cards]
        vals = [v for v in vals if v is not None]
        return max(vals) if vals else None

    tipo = best_rel.get("tipo_doc")
    if tipo in (None, "outros"):
        tipo = next((c.get("tipo_doc") for c in cards if c.get("tipo_doc") not in (None, "outros")), tipo)

    seen, resumos = set(), []
    for c in cards:
        if c.get("relevancia_merito") == "ruido":
            continue
        r = (c.get("resumo_ato") or "").strip()
        if r and r not in seen:
            seen.add(r)
            resumos.append(r)
    resumo = " ".join(resumos)[:_RESUMO_CAP] or (cards[0].get("resumo_ato") or "")

    out: dict = {
        "mov_id": cards[0].get("mov_id"),
        "resumo_ato": resumo,
        "tipo_doc": tipo,
        "relevancia_merito": best_rel.get("relevancia_merito", "baixa"),
        "decisao": best_dec.get("decisao") or {},
        "evento_garantia": eg,
        "valores": {
            "valor_debito_executado": vmax("valor_debito_executado"),
            "valor_garantia": vmax("valor_garantia"),
        },
        "data_inferida_ato": next((c.get("data_inferida_ato") for c in cards if c.get("data_inferida_ato")), None),
    }
    if cards[0].get("data"):
        out["data"] = cards[0]["data"]
    if any(("cdas" in c or "processos_citados" in c) for c in cards):  # ramo petição
        out["cdas"] = _union(cards, "cdas", "numero")
        out["processos_citados"] = _union(cards, "processos_citados", "cnj")
    return out


def sum_usage(usages: list[dict]) -> dict:
    """Soma tokens/custo dos N chunks; model/provider/variant do 1o."""
    out = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "cost_usd": 0.0}
    for u in usages:
        out["input_tokens"] += u.get("input_tokens", 0) or 0
        out["output_tokens"] += u.get("output_tokens", 0) or 0
        out["total_tokens"] += u.get("total_tokens", 0) or 0
        out["cost_usd"] += u.get("cost_usd", 0.0) or 0.0
    if usages:
        for k in ("model", "provider", "model_variant"):
            if usages[0].get(k) is not None:
                out[k] = usages[0][k]
    return out

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

# split_text/sum_usage genéricos + a orquestração map_reduce_classify moraram aqui;
# extraídos pro garantis_shared.llm_chunking (PR chunking shared 2026-06-22) pra L2/L3
# reusarem. split/reduce POR-LAYER do L1 (split_large_peca_variants/reduce_peca_cards)
# FICAM aqui. Re-export (alias redundante = re-export intencional, ruff não dropa) pra
# callers/tests existentes seguirem importando daqui: _split_text é usado internamente,
# sum_usage é só re-export.
from garantis_shared.llm_chunking import split_text as _split_text
from garantis_shared.llm_chunking import sum_usage as sum_usage

from .prompts_v4 import _doc_reading_profile
from .schemas import DocAnexado

CHUNK_SIZE = 180_000   # < 200k (margem pro marcador + mov + outros docs no prompt;
                       # 200k de prompt é o teto comprovado dos 60s)
_RESUMO_CAP = 3000
_REL = {"alta": 3, "media": 2, "baixa": 1, "ruido": 0}


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
    pieces = _split_text(big.text_content or "", size=CHUNK_SIZE)  # len>CHUNK_SIZE ⇒ ≥2 pedaços
    n = len(pieces)
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
        # processos_administrativos_citados NÃO estava aqui: o campo entrou no schema
        # com o v1.3 (WS-D admin refs) e o reduce não acompanhou, então TODA peça
        # chunkada (>180k) perdia os admin_item EM SILÊNCIO — card normal, custo
        # normal, referência faltando. Medido em prod 2026-08-05: das 10 petições
        # giants (>180k) com card ativo, 0% tem admin_item, contra 46,1% das 466
        # não-giants; as CDAs sobrevivem (34%) justamente porque já estavam no union.
        out["processos_administrativos_citados"] = _union(
            cards, "processos_administrativos_citados", "numero",
        )
    return out

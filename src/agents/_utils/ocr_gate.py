"""Gate de OCR/Vision — decide POR DOCUMENTO se vale mandar o PDF pro Gemini.

Porte do POC (prompt_monit_reader/l1_vision.py). 2 sinais determinísticos, sem LLM:

  SINAL 1 — PÁGINA-IMAGEM (PyMuPDF): página sem texto extraível, OU coberta por
     imagem ≥COBERTURA_IMG_MIN E texto ocupa <AREA_TEXTO_MAX da área (= scan com
     carimbo/rodapé; conteúdo preso na imagem). Por ÁREA, não por contagem de chars.
  SINAL 2 — TEXTO-LIXO (rmgarbage, Taghva et al. ISRI/UNLV 2001): fração de tokens
     "garbage" no text_content do provedor > GARBAGE_RATIO_MAX → texto corrompido.

Diferença vs POC: o ai-agents JÁ baixa o PDF via google-cloud-storage (vision.py),
então este módulo opera sobre BYTES (não baixa via gsutil). Fallback seguro: qualquer
falha → trata como "não precisa Vision" (fica no texto), nunca quebra.
"""
from __future__ import annotations

import re
from typing import Any, Optional

# Sinal 1 (página-imagem) — thresholds calibrados em banco real (memory l1-ocr-gating)
COBERTURA_IMG_MIN = 0.50
AREA_TEXTO_MAX = 0.15
# Sinal 2 (rmgarbage)
GARBAGE_RATIO_MAX = 0.30
# Piso de TEOR: abaixo disto o texto não decide sozinho (ver texto_decide_sozinho).
# 400 chars ≈ um parágrafo — carimbo do PJe e rodapé do ESAJ ficam em 285-399.
TEOR_MIN_CHARS = 400
# Controle de páginas
TETO_PAGINAS = 100
AMOSTRA_PONTAS = 30

_VOGAIS = "aeiouáéíóúâêôãõàèìòùAEIOUÁÉÍÓÚÂÊÔÃÕ"


# ── SINAL 2 — rmgarbage sobre o texto do provedor ─────────────────────────────
def _is_garbage_token(tok: str) -> bool:
    t = tok
    if len(t) >= 40:
        return True
    alnum = sum(c.isalnum() for c in t)
    if len(t) >= 4 and alnum / len(t) <= 0.5:
        return True
    if re.search(r"(.)\1{3,}", t):
        return True
    letras = [c for c in t if c.isalpha()]
    if len(letras) >= 3:
        v = sum(c in _VOGAIS for c in letras)
        cons = len(letras) - v
        if cons == 0 or v == 0:
            return True
        ratio = v / cons
        if ratio < 0.10 or ratio > 10:
            return True
    miolo = t[1:-1]
    if len(set(c for c in miolo if not c.isalnum())) >= 2:
        return True
    return False


def garbage_ratio(txt: Optional[str]) -> float:
    if not txt:
        return 1.0
    toks = re.findall(r"\S+", txt)
    if not toks:
        return 1.0
    return sum(_is_garbage_token(t) for t in toks) / len(toks)


def texto_lixo(txt: Optional[str]) -> bool:
    """Texto do provedor inutilizável: vazio ou garbage_ratio alto."""
    if not txt or not txt.strip():
        return True
    return garbage_ratio(txt) > GARBAGE_RATIO_MAX


def texto_decide_sozinho(txt: Optional[str]) -> bool:
    """True = dá pra confiar SÓ no texto e nem baixar o PDF pro Sinal 1.

    ⚠️ `not texto_lixo(txt)` NÃO basta, e era exatamente esse o curto-circuito do
    caller. rmgarbage (Sinal 2) mede CORRUPÇÃO DE CARACTERE — é cego pra texto
    limpo e vazio de conteúdo, que é a forma mais comum de scan no acervo:

      - "Para conferir o original, acesse o site https://esaj.tjsp.jus.br…" (5.339
        docs em prod) — só o rodapé de autenticação do ESAJ;
      - "Num. 123456789 - Pág. 1\\nAssinado eletronicamente por: TRIBUNAL…" (3.258)
        — só o carimbo de assinatura do PJe.

    Nos dois casos o texto é português impecável, `garbage_ratio` ≈ 0, e a PEÇA
    está presa na imagem. O Sinal 1 (área de imagem por página) foi escrito
    literalmente pra "scan com carimbo/rodapé" — e nunca rodava neles, porque o
    caller desistia antes de baixar o PDF. Medido 2026-08-10.

    Abaixo de TEOR_MIN_CHARS, então, quem decide é o PDF: baixa e deixa o Sinal 1
    olhar a área. Doc curto e legítimo (despacho de 1 linha) custa 1 fetch do GCS
    e continua no texto — o Sinal 1 vê página com texto nativo e diz não.
    """
    return not texto_lixo(txt) and len((txt or "").strip()) >= TEOR_MIN_CHARS


# ── SINAL 1 — página-imagem (PyMuPDF, sobre bytes) ────────────────────────────
def _cobertura_img(page) -> float:
    pa = abs(page.rect) or 1.0
    m = 0.0
    for img in page.get_images(full=True):
        for r in page.get_image_rects(img[0]):
            inter = r & page.rect
            if not inter.is_empty:
                m = max(m, abs(inter) / pa)
    return m


def _area_texto(page, pymupdf) -> float:
    pa = abs(page.rect) or 1.0
    a = 0.0
    for b in page.get_text("dict")["blocks"]:
        if b.get("type") == 0:
            a += abs(pymupdf.Rect(b["bbox"]))
    return a / pa


def _pagina_eh_imagem(page, pymupdf) -> bool:
    txt = page.get_text("text").strip()
    if not txt:
        return True
    return _cobertura_img(page) >= COBERTURA_IMG_MIN and _area_texto(page, pymupdf) < AREA_TEXTO_MAX


def analisar_pdf_bytes(pdf_bytes: bytes) -> Optional[dict]:
    """Mede o Sinal 1 por página sobre os BYTES do PDF + controle de páginas.
    Retorna {pdf_bytes (inteiro ou recortado), n_paginas, paginas_imagem, truncado,
    paginas_enviadas} ou None em qualquer falha (fallback: fica no texto)."""
    try:
        import pymupdf
    except Exception:
        return None
    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        n = len(doc)
        pgs_img = sum(1 for p in doc if _pagina_eh_imagem(p, pymupdf))
    except Exception:
        return None

    if n <= TETO_PAGINAS:
        return {"pdf_bytes": pdf_bytes, "n_paginas": n, "paginas_imagem": pgs_img,
                "truncado": False, "paginas_enviadas": n}

    # monstro: recorta começo + fim com pypdf
    try:
        import io
        from pypdf import PdfReader, PdfWriter
        reader = PdfReader(io.BytesIO(pdf_bytes))
        writer = PdfWriter()
        idxs = list(range(AMOSTRA_PONTAS)) + list(range(n - AMOSTRA_PONTAS, n))
        for i in idxs:
            writer.add_page(reader.pages[i])
        buf = io.BytesIO()
        writer.write(buf)
        return {"pdf_bytes": buf.getvalue(), "n_paginas": n, "paginas_imagem": pgs_img,
                "truncado": True, "paginas_enviadas": len(idxs)}
    except Exception:
        return {"pdf_bytes": pdf_bytes, "n_paginas": n, "paginas_imagem": pgs_img,
                "truncado": False, "paginas_enviadas": n}


def precisa_vision(text_content: Optional[str], pdf_bytes: Optional[bytes]) -> tuple[bool, dict]:
    """Decisão por documento: manda pro Vision se texto-lixo (Sinal 2) OU há
    página-imagem (Sinal 1). Retorna (manda, nota). Fallback: (False, {}).

    pdf_bytes pode ser None (sem PDF) → decide só pelo Sinal 2 (mas sem PDF não há
    o que mandar, então retorna False)."""
    lixo = texto_lixo(text_content)
    if not pdf_bytes:
        return False, {"fonte": "texto", "motivo": "sem PDF"}
    info = analisar_pdf_bytes(pdf_bytes)
    if not info:
        return False, {"fonte": "texto", "motivo": "falha ao analisar PDF (fallback texto)"}
    pgs_img = info.get("paginas_imagem", 0)
    if not lixo and pgs_img == 0:
        return False, {"fonte": "texto", "motivo": "texto OK + PDF tem texto nativo"}
    motivo = "texto-lixo (rmgarbage)" if lixo else f"{pgs_img}/{info['n_paginas']} pag-imagem"
    nota = {"fonte": "pdf_vision", "motivo": motivo, "pdf_paginas": info["n_paginas"],
            "paginas_imagem": pgs_img, "truncado": info.get("truncado", False)}
    if info.get("truncado"):
        nota["aviso"] = (f"PDF de {info['n_paginas']} pgs: enviadas {AMOSTRA_PONTAS} do "
                         f"inicio + {AMOSTRA_PONTAS} do fim (documento extenso).")
    return True, {"_nota": nota, "_pdf_bytes": info["pdf_bytes"]}


__all__ = [
    "texto_lixo", "texto_decide_sozinho", "garbage_ratio", "analisar_pdf_bytes",
    "precisa_vision", "COBERTURA_IMG_MIN", "AREA_TEXTO_MAX", "GARBAGE_RATIO_MAX",
    "TEOR_MIN_CHARS", "TETO_PAGINAS", "AMOSTRA_PONTAS",
]

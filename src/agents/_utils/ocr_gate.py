"""Gate de OCR/Vision — decide POR DOCUMENTO se vale mandar o PDF pro Gemini.

2 sinais determinísticos, sem LLM:

  SINAL 1 — PÁGINA INALCANÇÁVEL (PyMuPDF): página sem texto extraível, OU cujo
     texto ocupa <AREA_TEXTO_MAX da área E o conteúdo está preso em algo que
     nenhum extrator lê — imagem (raster, ≥COBERTURA_IMG_MIN) ou VETOR (corpo
     convertido em curvas). Por ÁREA, não por contagem de chars.
  SINAL 2 — TEXTO-LIXO (rmgarbage, Taghva et al. ISRI/UNLV 2001): fração de tokens
     "garbage" no text_content do provedor > GARBAGE_RATIO_MAX → texto corrompido.

Quem baixa o PDF é o `vision.py` (google-cloud-storage), então este módulo opera sobre
BYTES. Fallback seguro: qualquer falha → trata como "não precisa Vision" (fica no texto),
nunca quebra.
"""
from __future__ import annotations

import re
from typing import Optional

# Régua de teor ÚNICA, compartilhada com o piso de admissão do L1-petição no
# garantis-shared. ⛔ Import DURO de propósito: um fallback local aqui seria a 6ª
# cópia do mesmo predicado, que é a doença que este módulo está curando. O wheel
# do shared já é dependência declarada deste repo (requirements.txt).
from garantis_shared.texto_util import texto_util_len

# Sinal 1 (página-imagem) — thresholds calibrados em banco real
COBERTURA_IMG_MIN = 0.50
AREA_TEXTO_MAX = 0.15
# Sinal 1, ramo VETOR: texto convertido em CURVAS. Nenhum extrator alcança, e
# `get_images()` não vê nada (não é raster) — sem este ramo a página passa por
# born-digital. Medido em 91 páginas de 12 PDFs reais:
#
#   página VETOR  : 220 – 1.665 paths, 339-340 chars (só o carimbo), área 0,03
#   página TABELA : 217 – 413 paths, 1.531 – 2.625 chars, área 0,26 – 0,71
#
# ⚠️ A margem em PATHS é estreita (220 vs 217). Por isso o corte NÃO é o path
# sozinho: quem carrega a decisão é o `area_texto < AREA_TEXTO_MAX` (as páginas de
# tabela ficam em 0,26-0,71), e o `chars < VETOR_CHARS_MAX` fecha a outra margem —
# página de vetor só tem carimbo, página de formulário tem 1,5k+ de texto de verdade.
VETOR_PATHS_MIN = 200
VETOR_CHARS_MAX = 600
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

    ⚠️ `not texto_lixo(txt)` NÃO basta. rmgarbage (Sinal 2) mede CORRUPÇÃO DE
    CARACTERE — é cego pra texto limpo e vazio de conteúdo, que é a forma mais comum
    de scan no acervo:

      - "Para conferir o original, acesse o site https://esaj.tjsp.jus.br…" — só o
        rodapé de autenticação do ESAJ;
      - "Num. 123456789 - Pág. 1\\nAssinado eletronicamente por: TRIBUNAL…" — só o
        carimbo de assinatura do PJe.

    Nos dois casos o texto é português impecável, `garbage_ratio` ≈ 0, e a PEÇA
    está presa na imagem. O Sinal 1 (área de imagem por página) existe pra "scan com
    carimbo/rodapé" — e só roda se o caller baixar o PDF.

    Abaixo de TEOR_MIN_CHARS, então, quem decide é o PDF: baixa e deixa o Sinal 1
    olhar a área. Doc curto e legítimo (despacho de 1 linha) custa 1 fetch do GCS
    e continua no texto — o Sinal 1 vê página com texto nativo e diz não.

    🚨 E o piso é sobre o teor ÚTIL, não sobre `len()` — senão o próprio carimbo
    que este docstring descreve o derrota por MULTIPLICAÇÃO DE PÁGINAS: ele repete
    1× por página, e 6 × 340 = 2.044 ≥ 400 (a petição em vetor fica inalcançável).
    A régua é `garantis_shared.texto_util` — MESMA função que o piso de admissão
    do `fetch_peticao_doc` usa: uma régua comum, não um piso por caller.
    """
    return not texto_lixo(txt) and texto_util_len(txt) >= TEOR_MIN_CHARS


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


def _pagina_motivo(page, pymupdf) -> Optional[str]:
    """POR QUE esta página é inalcançável por texto — ou None se ela está OK.

    Ordem escolhida (não é só estilo): `area_texto` é a GUARDA PRIMÁRIA e sai na
    frente porque é ela que salva as páginas de tabela/formulário — elas têm
    217-413 vector paths (acima do corte de vetor) e seriam falso-positivo se o
    path decidisse sozinho. Sair cedo aqui também evita `get_images()` e
    `get_drawings()` na maioria das páginas, que são as chamadas caras."""
    txt = page.get_text("text").strip()
    if not txt:
        return "vazia"
    if _area_texto(page, pymupdf) >= AREA_TEXTO_MAX:
        return None
    if _cobertura_img(page) >= COBERTURA_IMG_MIN:
        return "imagem"
    if len(txt) < VETOR_CHARS_MAX and len(page.get_drawings()) >= VETOR_PATHS_MIN:
        return "vetor"
    return None


def _pagina_eh_imagem(page, pymupdf) -> bool:
    """Wrapper booleano — o nome pelo qual harnesses de investigação chamam o
    Sinal 1. 'imagem' aqui = inalcançável por texto (inclui vetor)."""
    return _pagina_motivo(page, pymupdf) is not None


def _reserializa(doc, pdf_bytes: bytes) -> bytes:
    """Recompõe o PDF a partir do `doc` que o Sinal 1 JÁ abriu — custo de provider
    e de I/O ZERO (o parse foi pago acima).

    `pymupdf.open` REPARA na abertura o que um parser estrito recusa, e o Gemini é
    estrito: ele responde `400 The document has no pages`, o `except` de
    `call_l1_with_vision_fallback` engole, e o card sai gravado com o PDF nunca lido.
    Onde não há o que reparar o tamanho não se mexe: o default `deflate=0` copia os
    streams já comprimidos como estão.

    🚨 **O CASO DOMINANTE NÃO É PDF CORROMPIDO — É HTML SERVIDO COMO PDF, e é por
    isso que `tobytes()` sozinho não basta.**
    ⛔ `pymupdf.open(stream=..., filetype="pdf")` **NÃO levanta** nele — `filetype`
    é DICA, não imposição (a mesma armadilha do memory `autos-html-filetype-e-dica`).
    Ele abre como XHTML: `is_pdf=False`, `metadata['format']='XHTML'`; daí
    `paginas_imagem=0` e `motivos={}`.
    E `doc.tobytes()` sobre doc não-PDF levanta `AssertionError` NUA: o `except`
    devolve os bytes originais, e o Gemini receberia XHTML rotulado
    `mime_type='application/pdf'` e responderia o mesmo `400 The document has no pages`.
    ⇒ Por isso o ramo `convert_to_pdf()`, que devolve um `%PDF` de verdade, lido pelo
    pypdf sem levantar.
    ⚠️ E a classe "PyMuPDF repara o que o parser estrito recusa" quase não existe no
    acervo (PDF real passa no `pypdf(strict=False)`). O valor deste helper está no
    ramo do HTML, não no do reparo.

    ⛔ Sem `garbage`/`deflate` de propósito. Encolher o blob mudaria QUANTO passa
    pelos caps inline do `vision.py` — é outra decisão, e pede medição própria.

    Falha ⇒ os bytes originais. O gate nunca quebra por causa disto.
    """
    try:
        # `is_pdf` é o discriminador certo: o `filetype='pdf'` da abertura é dica, e
        # um XHTML chega aqui como doc VÁLIDO e não-PDF.
        return doc.tobytes() if doc.is_pdf else doc.convert_to_pdf()
    except Exception:
        return pdf_bytes


def _recorta(pdf_bytes: bytes, idxs: list[int]) -> bytes:
    """As páginas `idxs` do PDF, com pypdf. Levanta em qualquer falha — o caller decide."""
    import io
    from pypdf import PdfReader, PdfWriter
    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter()
    for i in idxs:
        writer.add_page(reader.pages[i])
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def inicio_do_pdf(pdf_bytes: bytes, n_paginas: int) -> Optional[bytes]:
    """As `n_paginas` primeiras páginas — a JANELA do C5 para candidato scan, que é o
    equivalente em páginas do `head_chars` em texto. None em qualquer falha (o candidato
    segue sem PDF, e sem conteúdo o C5 não o afirma)."""
    try:
        from pypdf import PdfReader
        import io
        n = len(PdfReader(io.BytesIO(pdf_bytes)).pages)
        return pdf_bytes if n <= n_paginas else _recorta(pdf_bytes, list(range(n_paginas)))
    except Exception:
        return None


def analisar_pdf_bytes(pdf_bytes: bytes) -> Optional[dict]:
    """Mede o Sinal 1 por página sobre os BYTES do PDF + controle de páginas.
    Retorna {pdf_bytes (recomposto ou recortado), n_paginas, paginas_imagem,
    motivos, truncado, paginas_enviadas} ou None em qualquer falha (fallback: fica
    no texto). ⚠️ O `pdf_bytes` que sai NÃO é o que entrou: é o blob recomposto
    por `_reserializa` — quem manda ao Gemini tem que usar ESTE.

    ⚠️ O `None` de fallback NÃO é teórico: parte dos "PDFs" do cohort do gate são
    HTML ou RTF curtos servidos sob nome `.pdf` (começando com `<p>` ou
    `{\\rtf1`) — `pymupdf.open` levanta, e o certo é o documento ficar no
    caminho texto, de graça. Há teste prendendo que a exceção não vaza: se ela
    vazar, ela sobe pelo gate e derruba a cascade inteira."""
    try:
        import pymupdf
    except Exception:
        return None
    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        n = len(doc)
        motivos: dict[str, int] = {}
        # 🚨 Monstro: o Sinal 1 mede SÓ as páginas que vão subir (a amostra do recorte
        # abaixo). Medir as N custa ~55ms/pág — em autos de 1.000+ págs isso passa do
        # timeout do caller, e TODA passada cai em ReadTimeout com o C5 já pago. E
        # página-imagem FORA da amostra nunca chega ao Gemini: contá-la só mandaria
        # páginas textuais pro Vision, que é o uso vetado.
        # ⚠️ Exceção: se o `_recorta` abaixo levantar, sobe o doc inteiro, e aí imagem
        # só no miolo passa a ficar no texto. Aceito: recorte quebrado + scan só no
        # miolo + pontas textuais, e 1.000+ págs inline estourariam de qualquer jeito.
        idxs = (range(n) if n <= TETO_PAGINAS
                else [*range(AMOSTRA_PONTAS), *range(n - AMOSTRA_PONTAS, n)])
        for i in idxs:
            m = _pagina_motivo(doc[i], pymupdf)
            if m:
                motivos[m] = motivos.get(m, 0) + 1
        pgs_img = sum(motivos.values())
    except Exception:
        return None

    if n <= TETO_PAGINAS:
        return {"pdf_bytes": _reserializa(doc, pdf_bytes), "n_paginas": n,
                "paginas_imagem": pgs_img, "motivos": motivos,
                "truncado": False, "paginas_enviadas": n}

    # monstro: recorta começo + fim com pypdf
    try:
        return {"pdf_bytes": _recorta(pdf_bytes, idxs), "n_paginas": n,
                "paginas_imagem": pgs_img, "motivos": motivos, "truncado": True,
                "paginas_enviadas": len(idxs)}
    except Exception:
        # o recorte falhou: vai o documento inteiro, mas RECOMPOSTO — este ramo é
        # justamente o do PDF malformado, que é quem toma o 400 do Gemini.
        return {"pdf_bytes": _reserializa(doc, pdf_bytes), "n_paginas": n,
                "paginas_imagem": pgs_img, "motivos": motivos,
                "truncado": False, "paginas_enviadas": n}


def precisa_vision(text_content: Optional[str], pdf_bytes: Optional[bytes],
                   *, so_capa: bool = False) -> tuple[bool, dict]:
    """Decisão por documento: manda pro Vision se texto-lixo (Sinal 2) OU há
    página-imagem (Sinal 1). Retorna (manda, nota). Fallback: (False, {}).

    pdf_bytes pode ser None (sem PDF) → decide só pelo Sinal 2 (mas sem PDF não há
    o que mandar, então retorna False).

    `so_capa=True`: o caller já identificou QUE PEÇA este documento é (título literal
    / código / doctype) e sabe que o texto extraído é a CAPA, não o documento. Aí os
    2 Sinais estão respondendo a pergunta errada — eles decidem se dá pra CONFIAR no
    texto, e a resposta já veio de fora. Sem isto, uma petição cuja capa o extrator
    pegou limpa (rmgarbage ≈ 0, páginas com texto nativo) sairia por
    "texto OK + PDF tem texto nativo" e o corpo dela nunca seria lido.
    ⛔ NÃO é "PDF textual vai pro Vision" — o benchmark disso mediu lift ZERO, e segue
    vetado. O que muda aqui é que o texto extraído não é o documento.
    ⚠️ Os fallbacks NEGATIVOS ficam acima deste ramo de propósito: sem PDF e PDF
    ilegível continuam voltando (False, …) — é o fail-open, e ele não tem exceção."""
    lixo = texto_lixo(text_content)
    if not pdf_bytes:
        return False, {"fonte": "texto", "motivo": "sem PDF"}
    info = analisar_pdf_bytes(pdf_bytes)
    if not info:
        return False, {"fonte": "texto", "motivo": "falha ao analisar PDF (fallback texto)"}
    pgs_img = info.get("paginas_imagem", 0)
    if not lixo and pgs_img == 0 and not so_capa:
        return False, {"fonte": "texto", "motivo": "texto OK + PDF tem texto nativo"}
    # Motivo DISCRIMINADO (`pag-vetor` vs `pag-imagem`): sem isso, ligar o ramo de
    # vetor ficaria indistinguível na telemetria de "o gate de raster passou a
    # pegar mais" — e a pergunta que se faz depois do flip é exatamente qual dos
    # dois cresceu, porque o custo de cada um tem denominador diferente.
    detalhe = ", ".join(f"{v} pag-{k}" for k, v in sorted(info.get("motivos", {}).items()))
    if lixo:
        motivo = "texto-lixo (rmgarbage)"
    elif pgs_img:
        motivo = f"{pgs_img}/{info['n_paginas']} inalcancavel ({detalhe})"
    else:
        # ⭐ Rótulo PRÓPRIO, não `0/N inalcancavel ()`: este ramo só existe porque o
        # caller declarou que o texto é a capa, e na telemetria ele tem que ser
        # distinguível dos 2 Sinais — a pergunta depois do flip é qual dos três cresceu.
        motivo = f"peca-identificada-so-capa ({info['n_paginas']} pag)"
    nota = {"fonte": "pdf_vision", "motivo": motivo, "pdf_paginas": info["n_paginas"],
            "paginas_imagem": pgs_img, "motivos": info.get("motivos", {}),
            "truncado": info.get("truncado", False)}
    if info.get("truncado"):
        nota["aviso"] = (f"PDF de {info['n_paginas']} pgs: enviadas {AMOSTRA_PONTAS} do "
                         f"inicio + {AMOSTRA_PONTAS} do fim (documento extenso).")
    return True, {"_nota": nota, "_pdf_bytes": info["pdf_bytes"]}


__all__ = [
    "texto_lixo", "texto_decide_sozinho", "garbage_ratio", "analisar_pdf_bytes",
    "precisa_vision", "COBERTURA_IMG_MIN", "AREA_TEXTO_MAX", "GARBAGE_RATIO_MAX",
    "TEOR_MIN_CHARS", "TETO_PAGINAS", "AMOSTRA_PONTAS",
    "VETOR_PATHS_MIN", "VETOR_CHARS_MAX",
]

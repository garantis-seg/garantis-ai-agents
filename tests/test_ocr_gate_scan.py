"""Sinal 1, ramo IMAGEM: a página escaneada sai como imagem SEM decodificar a imagem.

O gate roda síncrono dentro do event loop do serviço. Decodificar a imagem de cada
página custa centenas de ms de CPU por página escaneada, e um scan de dezenas de
páginas trava todo request da instância até o caller desistir. O gate só precisa da
GEOMETRIA: o bbox de cada imagem e o de cada bloco de texto.

⚠️ As fixtures são SINTÉTICAS, geradas em runtime com PyMuPDF. ⛔ Não commitar PDF
real de cliente.
"""
from __future__ import annotations

import pytest

pymupdf = pytest.importorskip("pymupdf")

from src.agents._utils.ocr_gate import (  # noqa: E402
    COBERTURA_IMG_MIN,
    _cobertura_img,
    _pagina_motivo,
    analisar_pdf_bytes,
)

# O único texto nativo de um scan costuma ser o carimbo do tribunal: pouca área.
CARIMBO = "Documento assinado eletronicamente. Para conferir o original, acesse o site."
PAGINA_INTEIRA = [(0.0, 0.0, 1.0, 1.0)]


def _scan(n_paginas: int, areas=PAGINA_INTEIRA) -> bytes:
    """Páginas de scan: 1 imagem por área (x0, y0, x1, y1 em fração da página) e o
    carimbo no rodapé."""
    doc = pymupdf.open()
    pix = pymupdf.Pixmap(pymupdf.csGRAY, pymupdf.IRect(0, 0, 60, 80))
    pix.set_rect(pix.irect, (200,))
    for _ in range(n_paginas):
        page = doc.new_page()
        w, h = page.rect.width, page.rect.height
        for x0, y0, x1, y1 in areas:
            page.insert_image(pymupdf.Rect(x0 * w, y0 * h, x1 * w, y1 * h),
                              pixmap=pix, keep_proportion=False)
        page.insert_text((30, h - 20), CARIMBO, fontsize=6)
    return doc.tobytes()


def test_scan_vira_imagem_sem_decodificar_a_imagem(monkeypatch):
    """⛔ MUTANTES: toda rota que DECODIFICA a imagem só para medir a página.
    - `get_image_rects(xref)`: Pixmap + hash de todas as imagens, para casar o xref.
    - `get_image_info(hashes=True)` ou `xrefs=True`: o mesmo hash.
    - `get_text("dict")` com `TEXT_PRESERVE_IMAGES`: re-encoda em PNG toda imagem que
      não é JPEG.
    Aqui elas levantam, o `except` do `analisar_pdf_bytes` devolve None, e o scan fica
    no texto."""
    pdf = _scan(3)

    def _decodificou(*_args, **_kwargs):
        raise AssertionError("o gate decodificou a imagem só para medir a página")

    info_real = pymupdf.Page.get_image_info
    texto_real = pymupdf.Page.get_text

    def _info(page, hashes=False, xrefs=False):
        if hashes or xrefs:
            _decodificou()
        return info_real(page)

    def _texto(page, *args, **kwargs):
        opcao = args[0] if args else kwargs.get("option", "text")
        flags = kwargs.get("flags", args[2] if len(args) > 2 else None)
        if opcao == "dict" and (flags is None or flags & pymupdf.TEXT_PRESERVE_IMAGES):
            _decodificou()
        return texto_real(page, *args, **kwargs)

    monkeypatch.setattr(pymupdf.Page, "get_image_rects", _decodificou)
    monkeypatch.setattr(pymupdf.Page, "get_image_info", _info)
    monkeypatch.setattr(pymupdf.Page, "get_text", _texto)
    info = analisar_pdf_bytes(pdf)
    assert info is not None, "o gate falhou ao medir o scan"
    assert info["motivos"] == {"imagem": 3}


def test_cobertura_e_a_fracao_da_pagina_que_a_imagem_cobre():
    """A geometria continua a mesma: imagem num quarto da página cobre 0,25, e a página
    com o carimbo fica no texto. ⛔ MUTANTE: contar qualquer imagem como página inteira."""
    doc = pymupdf.open(stream=_scan(1, [(0.0, 0.0, 0.5, 0.5)]), filetype="pdf")
    assert _cobertura_img(doc[0]) == pytest.approx(0.25, abs=0.01)
    assert _cobertura_img(doc[0]) < COBERTURA_IMG_MIN
    assert _pagina_motivo(doc[0], pymupdf) is None


def test_cobertura_e_a_da_maior_imagem_nao_a_soma():
    """2 imagens de 30% da página cada: a cobertura é 0,30, a da maior UMA, e a página
    fica no texto. ⛔ MUTANTE: somar as imagens (0,60) mandaria a página ao Vision."""
    tiras = [(0.0, 0.0, 1.0, 0.3), (0.0, 0.5, 1.0, 0.8)]
    doc = pymupdf.open(stream=_scan(1, tiras), filetype="pdf")
    assert _cobertura_img(doc[0]) == pytest.approx(0.30, abs=0.01)
    assert _pagina_motivo(doc[0], pymupdf) is None

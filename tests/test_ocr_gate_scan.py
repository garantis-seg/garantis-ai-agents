"""Sinal 1, ramo IMAGEM: a página escaneada sai como imagem SEM decodificar a imagem.

⚠️ As fixtures são SINTÉTICAS, geradas em runtime com PyMuPDF. ⛔ Não commitar PDF
real de cliente.
"""
from __future__ import annotations

import pytest

pymupdf = pytest.importorskip("pymupdf")

from src.agents._utils.ocr_gate import (  # noqa: E402
    _cobertura_img,
    _pagina_motivo,
    analisar_pdf_bytes,
)

# O único texto nativo de um scan costuma ser o carimbo do tribunal: pouca área.
CARIMBO = "Documento assinado eletronicamente. Para conferir o original, acesse o site."


def _scan(n_paginas: int, areas=((0.0, 0.0, 1.0, 1.0),)) -> bytes:
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
    - Qualquer outra rota do Python que gere o Pixmap da imagem: o guarda fica na
      PROPRIEDADE (`fz_get_pixmap_from_image`), não só no nome das 3 APIs acima.
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
    monkeypatch.setattr(pymupdf.mupdf, "fz_get_pixmap_from_image", _decodificou)
    info = analisar_pdf_bytes(pdf)
    assert info is not None, "o gate falhou ao medir o scan"
    assert info["motivos"] == {"imagem": 3}


def test_scan_inline_e_imagem():
    """A imagem inline (BI ... ID ... EI) não tem xref, e o `get_images()` não a lista:
    o código antigo deixava o scan inline no texto. ⛔ MUTANTE: medir a cobertura só
    pelas imagens com xref."""
    doc = pymupdf.open()
    page = doc.new_page()
    w, h = page.rect.width, page.rect.height
    page.insert_text((30, h - 20), CARIMBO, fontsize=6)
    xref = page.get_contents()[0]
    # 1 pixel cinza, esticado na página inteira e desenhado inline.
    inline = b"q %g 0 0 %g 0 0 cm BI /W 1 /H 1 /CS /G /BPC 8 ID \xc8 EI Q\n" % (w, h)
    doc.update_stream(xref, inline + doc.xref_stream(xref))
    p = pymupdf.open(stream=doc.tobytes(), filetype="pdf")[0]
    assert p.get_images() == [], "premissa: a imagem é inline, sem xref"
    assert _cobertura_img(p) == pytest.approx(1.0, abs=0.01)
    assert _pagina_motivo(p, pymupdf) == "imagem"


def test_cobertura_e_a_area_da_maior_imagem():
    """2 imagens de 0,6 x 0,5 da página: a cobertura é a ÁREA da maior UMA (0,30), e a
    página com o carimbo fica no texto. ⛔ MUTANTES: somar as imagens (0,60), contar
    qualquer imagem como página inteira (1,0), medir só a altura (0,5) ou só a largura
    (0,6)."""
    areas = [(0.0, 0.0, 0.6, 0.5), (0.4, 0.5, 1.0, 1.0)]
    doc = pymupdf.open(stream=_scan(1, areas), filetype="pdf")
    assert _cobertura_img(doc[0]) == pytest.approx(0.30, abs=0.01)
    assert _pagina_motivo(doc[0], pymupdf) is None

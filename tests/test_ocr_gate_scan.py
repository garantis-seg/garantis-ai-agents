"""Sinal 1, ramo IMAGEM: a página escaneada sai como imagem SEM decodificar a imagem.

O gate roda síncrono dentro do event loop do serviço. Decodificar a imagem de cada
página custa centenas de ms de CPU por página escaneada, e um scan de dezenas de
páginas trava todo request da instância até o caller desistir. A cobertura só precisa
da GEOMETRIA (o bbox), e `get_image_info()` a dá sem decodificar nada.

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


def _scan(n_paginas: int, quarto: bool = False) -> bytes:
    """Páginas de scan: 1 imagem (a página inteira, ou o quarto de cima à esquerda) e o
    carimbo no rodapé."""
    doc = pymupdf.open()
    pix = pymupdf.Pixmap(pymupdf.csGRAY, pymupdf.IRect(0, 0, 60, 80))
    pix.set_rect(pix.irect, (200,))
    for _ in range(n_paginas):
        page = doc.new_page()
        r = page.rect
        alvo = pymupdf.Rect(0, 0, r.width / 2, r.height / 2) if quarto else r
        page.insert_image(alvo, pixmap=pix, keep_proportion=False)
        page.insert_text((30, r.height - 20), CARIMBO, fontsize=6)
    return doc.tobytes()


def test_scan_vira_imagem_sem_decodificar_a_imagem(monkeypatch):
    """⛔ MUTANTE: voltar a `get_images()` + `get_image_rects(xref)` no `_cobertura_img`.
    O `get_image_rects` decodifica a imagem (Pixmap + hash de todas as da página) só
    para casar o xref. Aqui ele levanta, o `except` do `analisar_pdf_bytes` devolve
    None, e o scan fica no texto."""
    def _decodifica(*_args, **_kwargs):
        raise AssertionError("o gate decodificou a imagem só para achar o retângulo")

    monkeypatch.setattr(pymupdf.Page, "get_image_rects", _decodifica)
    info = analisar_pdf_bytes(_scan(3))
    assert info is not None, "o gate falhou ao medir o scan"
    assert info["motivos"] == {"imagem": 3}


def test_cobertura_e_a_fracao_da_pagina_que_a_imagem_cobre():
    """A geometria continua a mesma: imagem num quarto da página cobre 0,25, e a página
    com o carimbo fica no texto. ⛔ MUTANTE: contar qualquer imagem como página inteira."""
    doc = pymupdf.open(stream=_scan(1, quarto=True), filetype="pdf")
    assert _cobertura_img(doc[0]) == pytest.approx(0.25, abs=0.01)
    assert _cobertura_img(doc[0]) < COBERTURA_IMG_MIN
    assert _pagina_motivo(doc[0], pymupdf) is None

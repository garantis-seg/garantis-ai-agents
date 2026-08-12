"""Sinal 1, ramo VETOR: texto convertido em curvas é tão inalcançável quanto scan.

O caso (MS 1012150-95.2026.8.26.0224, 2026-08-12): o TJSP exportou a petição
inicial com o corpo em ~1.000 vector paths por página. Não é raster — `get_images()`
não vê nada — então a página passava como born-digital, e o único texto extraível
era o carimbo de autenticação. O AIIM que ligaria dois conexos ficou preso no PDF.

⚠️ As fixtures são SINTÉTICAS, geradas em runtime com PyMuPDF. ⛔ Não commitar PDF
real de cliente. Os números (paths, chars, área) vêm de 91 páginas de 12 PDFs reais
medidas pelo painel adversarial — em particular as 3 páginas-ARMADILHA: formulários
e tabelas de texto legítimo com 217, 261 e 413 paths, que um corte por path sozinho
mandaria pro Vision.
"""
from __future__ import annotations

import pytest

pymupdf = pytest.importorskip("pymupdf")

from src.agents._utils.ocr_gate import (  # noqa: E402
    VETOR_CHARS_MAX,
    VETOR_PATHS_MIN,
    _pagina_motivo,
    analisar_pdf_bytes,
    precisa_vision,
)

CARIMBO = ("Para conferir o original, acesse o site https://esaj.tjsp.jus.br/"
           "pastadigital/pg/abrirConferenciaDocumento.do, informe o processo "
           "1012150-95.2026.8.26.0224 e codigo l4Q1NmsN. fls. 1")


def _pagina(doc, *, paths: int, texto: str, tamanho: int = 9):
    """1 página com N vector paths e um bloco de texto de tamanho controlado."""
    page = doc.new_page()
    for i in range(paths):
        y = 20 + (i % 700)
        page.draw_line(pymupdf.Point(30, y), pymupdf.Point(40 + (i % 300), y))
    if texto:
        page.insert_textbox(pymupdf.Rect(30, 40, 560, 780), texto,
                            fontsize=tamanho, fontname="helv")
    return page


def _pdf(paginas: list[dict]) -> bytes:
    doc = pymupdf.open()
    for p in paginas:
        _pagina(doc, **p)
    return doc.tobytes()


# ── O caso-alvo ──────────────────────────────────────────────────────────────
def test_pagina_vetor_so_com_carimbo_e_inalcancavel():
    """Corpo em curvas + carimbo: 879-1.490 paths e 339 chars nos PDFs reais."""
    doc = pymupdf.open(stream=_pdf([{"paths": 900, "texto": CARIMBO}]), filetype="pdf")
    assert _pagina_motivo(doc[0], pymupdf) == "vetor"


def test_pagina_vazia_continua_sendo_pega_pelo_ramo_de_sempre():
    doc = pymupdf.open(stream=_pdf([{"paths": 0, "texto": ""}]), filetype="pdf")
    assert _pagina_motivo(doc[0], pymupdf) == "vazia"


# ── As 3 armadilhas: texto LEGÍTIMO com muitos paths ─────────────────────────
@pytest.mark.parametrize("paths,rotulo", [
    (217, "GUIA 867186 pg1 (2.625 chars)"),
    (261, "decisao DTJ 867161 pg5"),
    (413, "DOC DIVERSOS 867192 pg1"),
])
def test_formulario_e_tabela_com_paths_acima_do_corte_NAO_vao_pro_vision(paths, rotulo):
    """🚨 O falso-positivo que custaria dinheiro em escala: as 3 têm MAIS paths que o
    corte (200) e são texto perfeitamente legível. Quem as salva é o `area_texto` —
    e, na margem, o teto de chars. A margem real medida é 220-vs-217, não 879-vs-11:
    o path NUNCA decide sozinho."""
    conteudo = ("A Fazenda Publica do Estado, por seu procurador, requer a juntada "
                "dos documentos que instruem a presente. ") * 24
    doc = pymupdf.open(stream=_pdf([{"paths": paths, "texto": conteudo, "tamanho": 11}]),
                       filetype="pdf")
    pagina = doc[0]
    assert len(pagina.get_text("text").strip()) > VETOR_CHARS_MAX, rotulo
    assert _pagina_motivo(pagina, pymupdf) is None, rotulo


def test_born_digital_sem_paths_nunca_vai_pro_vision():
    conteudo = "EXCELENTISSIMO SENHOR DOUTOR JUIZ DE DIREITO. " * 40
    doc = pymupdf.open(stream=_pdf([{"paths": 0, "texto": conteudo, "tamanho": 11}]),
                       filetype="pdf")
    assert _pagina_motivo(doc[0], pymupdf) is None


def test_a_margem_APERTADA_de_falso_positivo_area_baixa_com_texto_de_verdade():
    """🚨 O caso que o `area_texto` sozinho NÃO salva, e por isso o teto de chars
    existe: a GUIA 867186 pg2 tem área 0,12 (ABAIXO do corte de 0,15) e 1.531 chars
    de texto legível. Fonte pequena numa página grande derruba a área sem derrubar o
    conteúdo. Sem o `chars < VETOR_CHARS_MAX`, esta página vira Vision pago à toa.

    ⛔ Mutante alvo: tirar o `len(txt) < VETOR_CHARS_MAX` do ramo de vetor."""
    doc = pymupdf.open()
    page = doc.new_page()
    for i in range(300):                       # acima do corte de paths
        page.draw_line(pymupdf.Point(20, 20 + i), pymupdf.Point(60, 20 + i))
    page.insert_textbox(pymupdf.Rect(300, 300, 560, 420),
                        "conteudo real da guia de recolhimento estadual. " * 40,
                        fontsize=4, fontname="helv")
    p = pymupdf.open(stream=doc.tobytes(), filetype="pdf")[0]
    from src.agents._utils.ocr_gate import AREA_TEXTO_MAX, _area_texto
    assert _area_texto(p, pymupdf) < AREA_TEXTO_MAX, "premissa: área abaixo do corte"
    assert len(p.get_text("text").strip()) > VETOR_CHARS_MAX
    assert _pagina_motivo(p, pymupdf) is None


def test_o_corte_de_paths_sozinho_nao_basta_e_o_teste_prova():
    """Prende a COMPOSIÇÃO. Se alguém trocar o `and` por `or` no ramo de vetor —
    ou tirar o `area_texto` da frente — este teste é o que reprova."""
    conteudo = "texto denso ocupando a pagina inteira. " * 60
    doc = pymupdf.open(
        stream=_pdf([{"paths": VETOR_PATHS_MIN + 500, "texto": conteudo, "tamanho": 12}]),
        filetype="pdf")
    assert _pagina_motivo(doc[0], pymupdf) is None


# ── Telemetria: o motivo é DISCRIMINADO ──────────────────────────────────────
def test_motivo_separa_vetor_de_imagem():
    """Sem isto, ligar o ramo de vetor fica indistinguível de 'o gate de raster
    passou a pegar mais' — e a pergunta pós-flip é exatamente qual dos dois cresceu."""
    info = analisar_pdf_bytes(_pdf([{"paths": 900, "texto": CARIMBO},
                                    {"paths": 900, "texto": CARIMBO}]))
    assert info["motivos"] == {"vetor": 2}
    manda, nota = precisa_vision(CARIMBO * 6, _pdf([{"paths": 900, "texto": CARIMBO}]))
    assert manda is True
    assert "pag-vetor" in nota["_nota"]["motivo"]


# ── Fallback: "PDF" que não é PDF ────────────────────────────────────────────
@pytest.mark.parametrize("corpo", [
    b"<p>Access Denied</p>",                       # HTML sob nome .pdf
    b"{\\rtf1\\ansi\\deff0 texto}",                # RTF sob nome .pdf
    b"",                                           # vazio
    b"%PDF-1.4 truncado no meio",                  # header certo, corpo quebrado
])
def test_bytes_que_nao_sao_pdf_ficam_no_texto_sem_vazar_excecao(corpo):
    """6 de 20 'PDFs' de uma amostra do cohort do gate são HTML/RTF de 42-946 bytes
    servidos com nome `.pdf`. O comportamento certo (ficar no texto, custo zero) já
    existia e não tinha teste: uma refatoração que deixasse a exceção vazar derrubaria
    a cascade inteira, porque o gate roda dentro dela."""
    assert analisar_pdf_bytes(corpo) is None
    manda, nota = precisa_vision("texto qualquer", corpo)
    assert manda is False
    assert nota["fonte"] == "texto"


if __name__ == "__main__":  # smoke sem pytest
    test_pagina_vetor_so_com_carimbo_e_inalcancavel()
    test_born_digital_sem_paths_nunca_vai_pro_vision()
    print("ok")

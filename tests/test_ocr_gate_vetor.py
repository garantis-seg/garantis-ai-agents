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

import io

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




# ── O blob que sai é RECOMPOSTO, não o que entrou ────────────────────────────
def test_pdf_que_parser_estrito_recusa_sai_RECOMPOSTO_do_gate():
    """🚨 O 400 `The document has no pages`: o PyMuPDF repara na abertura, o Gemini
    não. O gate já pagou o `open` pelo Sinal 1, então recompor sai de graça.

    ⛔ MUTANTE: devolver `pdf_bytes` cru reprova aqui — e o modo de falha real é
    MUDO (gate aprova, payload monta, o Gemini levanta, o `except` cai no texto e o
    card fica gravado como saudável)."""
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError, PdfStreamError

    inteiro = _pdf([{"paths": 900, "texto": CARIMBO}] * 3)
    # sem xref NEM trailer — o que sobra de um PDF truncado no transporte
    quebrado = inteiro[:inteiro.rfind(b"xref")]

    with pytest.raises((PdfStreamError, PdfReadError)):
        PdfReader(io.BytesIO(quebrado), strict=False)

    manda, info = precisa_vision(CARIMBO * 6, quebrado)
    assert manda is True, "premissa: o gate aprova (corpo em vetor)"
    saindo = info["_pdf_bytes"]
    assert saindo != quebrado, "o gate tem que entregar o blob RECOMPOSTO"
    assert len(PdfReader(io.BytesIO(saindo), strict=False).pages) == 3


def test_pdf_sadio_atravessa_o_gate_sem_perder_pagina():
    """A outra metade: recompor não pode mexer no caso comum (99%+ do volume)."""
    inteiro = _pdf([{"paths": 900, "texto": CARIMBO}] * 3)
    from pypdf import PdfReader

    _manda, info = precisa_vision(CARIMBO * 6, inteiro)
    assert len(PdfReader(io.BytesIO(info["_pdf_bytes"]), strict=False).pages) == 3


def test_a_GUARDA_PRIMARIA_area_texto_salva_pagina_com_imagem_de_fundo():
    """⛔ MUTANTE: remover o early-return `area_texto >= AREA_TEXTO_MAX` do
    `_pagina_motivo` sobrevivia a toda a suíte — as fixtures de tabela acima são
    salvas pelo TETO DE CHARS, não pela área.

    O que ficava exposto é o ramo de IMAGEM: página com texto nativo POR CIMA de um
    fundo escaneado (`cobertura_img >= 0,50`) viraria falso-positivo e iria pro
    Vision pago. É custo, não silêncio — e é o cohort de scan com OCR embutido, que
    não é raro. O comentário do código diz que a área "é quem carrega a decisão";
    este teste é o que torna a frase verificável."""
    doc = pymupdf.open()
    page = doc.new_page()
    # imagem cobrindo a página inteira (o discriminador do ramo raster)
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 60, 80))
    pix.set_rect(pix.irect, (220, 220, 220))
    page.insert_image(page.rect, pixmap=pix)
    # ...com texto nativo de verdade por cima (o que o OCR embutido produz)
    page.insert_textbox(pymupdf.Rect(30, 40, 560, 780),
                        "SENTENCA. Vistos e examinados os autos. " * 60,
                        fontsize=12, fontname="helv")
    p = pymupdf.open(stream=doc.tobytes(), filetype="pdf")[0]
    from src.agents._utils.ocr_gate import AREA_TEXTO_MAX, _area_texto, _cobertura_img
    assert _cobertura_img(p) >= 0.50, "premissa: imagem cobre a pagina"
    assert _area_texto(p, pymupdf) >= AREA_TEXTO_MAX, "premissa: texto ocupa a pagina"
    assert _pagina_motivo(p, pymupdf) is None


if __name__ == "__main__":  # smoke sem pytest
    test_pagina_vetor_so_com_carimbo_e_inalcancavel()
    test_born_digital_sem_paths_nunca_vai_pro_vision()
    print("ok")


def test_html_servido_como_pdf_sai_do_gate_como_PDF_DE_VERDADE():
    """⛔ MUTANTE: trocar `doc.tobytes() if doc.is_pdf else doc.convert_to_pdf()` por
    `doc.tobytes()` sozinho — que foi a 1a versao deste fix, e era NO-OP no cohort
    inteiro que ela tinha por alvo.

    Medido em prod 2026-08-17: dos 85 cards cegos, **71 (83,5%) tem
    `file_format='html'`**, e nos 19 do cohort ATIVO sao **19 de 19**. Sao XHTML
    servidos sob nome `.pdf`.

    A cadeia do defeito, cada elo verificado por execucao:
      1. `pymupdf.open(stream=..., filetype='pdf')` NAO levanta — `filetype` e DICA
         (memory `autos-html-filetype-e-dica-nao-imposicao-2026-08-11`). Abre como
         XHTML: `is_pdf=False`, `metadata['format']='XHTML'`.
      2. logo `paginas_imagem=0` e `motivos={}` -> e o `motivo: null` dos 19 cards.
      3. `doc.tobytes()` sobre nao-PDF levanta `AssertionError` NUA;
      4. o `except` devolvia o MESMO objeto, o Gemini recebia XHTML rotulado
         `application/pdf` e respondia o mesmo `400 The document has no pages`.

    Este teste falha se alguem "simplificar" o ramo de volta."""
    from src.agents._utils.ocr_gate import _reserializa

    xhtml = (
        b'<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" '
        b'"http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">'
        b'<html xmlns="http://www.w3.org/1999/xhtml"><body>'
        + b"<p>EXCELENTISSIMO SENHOR DOUTOR JUIZ DE DIREITO</p>" * 40
        + b"</body></html>"
    )
    doc = pymupdf.open(stream=xhtml, filetype="pdf")

    # as premissas do caso real, antes da conclusao
    assert not doc.is_pdf, "premissa: o filetype='pdf' e dica; isto abriu como XHTML"
    assert doc.metadata.get("format") == "XHTML"

    out = _reserializa(doc, xhtml)

    assert out is not xhtml, "o gate devolveu o MESMO objeto: o fix virou no-op"
    assert out[:5] == b"%PDF-", f"o Gemini recebe {out[:8]!r} rotulado application/pdf"

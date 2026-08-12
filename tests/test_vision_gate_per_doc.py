"""O gate decide por PAR (texto do doc i, PDF do doc i) — e diz o que decidiu.

Dois furos fechados aqui, os dois medidos no MS 1012150-95.2026.8.26.0224:

1. **O curto-circuito** (`texto_decide_sozinho` antes do download): o carimbo do
   tribunal repete 1× por página, então 6 × 340 = 2.044 ≥ TEOR_MIN_CHARS=400 e o PDF
   nunca era baixado. O gate de página — o único lugar que sabe ler vetor — era
   inalcançável. Mesma aritmética que derrotava o piso de 2.000 do identify.
2. **O par errado**: a petição vai pro prompt CONCATENADA num entry só. Se o gate
   ler esse entry, ele julga o texto somado de N documentos contra o `gcs_url` de UM
   — no caso real, o do AGRAVO, que não contém o número procurado.
"""
from __future__ import annotations

import asyncio

import pytest

pymupdf = pytest.importorskip("pymupdf")

from src.agents._utils import vision as V  # noqa: E402
from src.agents._utils.ocr_gate import TEOR_MIN_CHARS, texto_decide_sozinho  # noqa: E402

CARIMBO_PAGINA = (
    "Para conferir o original, acesse o site https://esaj.tjsp.jus.br/pastadigital/pg/"
    "abrirConferenciaDocumento.do, informe o processo 1012150-95.2026.8.26.0224 e "
    "código l4Q1NmsN.\nEste documento é cópia do original, assinado digitalmente por "
    "ANGELO BUENO PASCHOINI, protocolado em 13/07/2026 às 17:49 , sob o número "
    "10121509520268260224.\nfls. {n}\n\n"
)
CARIMBO_6_PAGINAS = "".join(CARIMBO_PAGINA.format(n=i) for i in range(1, 7))


def _pdf_vetor() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    for i in range(900):
        page.draw_line(pymupdf.Point(30, 20 + (i % 700)),
                       pymupdf.Point(40 + (i % 300), 20 + (i % 700)))
    page.insert_textbox(pymupdf.Rect(30, 40, 560, 80), CARIMBO_PAGINA.format(n=1),
                        fontsize=6, fontname="helv")
    return doc.tobytes()


def _pdf_texto() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_textbox(pymupdf.Rect(30, 40, 560, 780),
                        "AGRAVO DE INSTRUMENTO. Razoes recursais. " * 60,
                        fontsize=11, fontname="helv")
    return doc.tobytes()


# ── 1. O curto-circuito ──────────────────────────────────────────────────────
def test_ANCORA_carimbo_de_6_paginas_nao_decide_sozinho():
    """⛔ ESTE é o teste que REPROVA o desenho anterior do pacote. Enquanto o piso
    media `len()` cru, 2.044 ≥ 400 e o PDF nunca descia."""
    assert len(CARIMBO_6_PAGINAS) > TEOR_MIN_CHARS * 5, "premissa: passa do piso CRU"
    assert not texto_decide_sozinho(CARIMBO_6_PAGINAS)


def test_peca_de_verdade_continua_decidindo_sozinha_e_NAO_baixa_pdf():
    """A outra metade: o custo do Vision é ∝ nº de docs inalcançáveis, não ao total.
    Se isto quebrar, todo documento do acervo passa a baixar PDF."""
    assert texto_decide_sozinho("Trata-se de acao anulatoria de debito fiscal. " * 20)


# ── 2. O par por documento + o veredito ──────────────────────────────────────
def _roda(pares, *, fetched):
    """call_l1_with_vision_fallback com GCS e LLM fakes. Devolve (gate, pdfs_enviados)."""
    enviados: list[bytes] = []

    async def _fake_fetch(urls):
        return [fetched[u] for u in urls if fetched.get(u)]

    async def _fake_vision(provider, *, pdf_bytes_list, **kw):
        enviados.extend(pdf_bytes_list)
        return "RESPOSTA_VISION"

    class _P:
        async def agenerate(self, **kw):
            return "RESPOSTA_TEXTO"

    gate: dict = {}
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(V, "fetch_pdfs_from_gcs", _fake_fetch)
        mp.setattr(V, "call_vision_l1", _fake_vision)
        # A flag vai pelo ENV de verdade (o `flag_enabled` é importado DENTRO da
        # função): monkeypatchar o símbolo do módulo não teria efeito nenhum e o
        # teste passaria contando a história errada de por que passou.
        mp.setenv("VISION_L1_ENABLED", "true")
        out = asyncio.run(V.call_l1_with_vision_fallback(
            _P(), model="m", prompt="p", response_schema=None,
            gcs_urls=[u for _t, u in pares], docs_text=pares, gate_out=gate,
        ))
    return gate, enviados, out


def test_manda_o_PDF_DO_DOC_CERTO_quando_o_conjunto_e_misto():
    """O conjunto do caso real: 1 agravo com texto de verdade + 1 petição em vetor.
    Só o segundo pode subir — e tem que ser o PDF DELE."""
    agravo, peticao = _pdf_texto(), _pdf_vetor()
    pares = [("AGRAVO DE INSTRUMENTO. Razoes recursais. " * 60, "gs://b/agravo.pdf"),
             (CARIMBO_6_PAGINAS, "gs://b/peticao.pdf")]
    gate, enviados, _ = _roda(
        pares, fetched={"gs://b/agravo.pdf": agravo, "gs://b/peticao.pdf": peticao})
    assert len(enviados) == 1
    assert enviados[0][:8] == peticao[:8], "subiu o PDF do documento errado"
    assert gate == {"n_docs": 2, "n_inalcancaveis": 1, "n_enviados": 1, "motivo": "vetor"}


def test_veredito_registra_ZERO_ENVIADO_quando_a_call_vision_falha():
    """`n_enviados` conta o que o Gemini REALMENTE recebeu. Se a chamada falha e cai
    no texto, o card é CEGO — e a sentinela tem que dizer isso, não o contrário."""
    async def _boom(*a, **kw):
        raise RuntimeError("Gemini 400: document has no pages")

    gate: dict = {}

    class _P:
        async def agenerate(self, **kw):
            return "RESPOSTA_TEXTO"

    async def _fake_fetch(urls):
        return [_pdf_vetor()]

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(V, "fetch_pdfs_from_gcs", _fake_fetch)
        mp.setattr(V, "call_vision_l1", _boom)
        mp.setenv("VISION_L1_ENABLED", "true")
        out = asyncio.run(V.call_l1_with_vision_fallback(
            _P(), model="m", prompt="p", response_schema=None,
            gcs_urls=["gs://b/p.pdf"],
            docs_text=[(CARIMBO_6_PAGINAS, "gs://b/p.pdf")], gate_out=gate,
        ))
    assert out == "RESPOSTA_TEXTO"
    assert gate["n_inalcancaveis"] == 1
    assert gate["n_enviados"] == 0


def test_cap_de_pdfs_por_chamada_vale_no_gate_per_doc():
    """O cap de `fetch_pdfs_from_gcs` NÃO alcança este ramo (aqui o fetch é 1 URL por
    vez) e o conjunto da petição vai até 25 documentos. Sem o corte, estoura a janela."""
    vetor = _pdf_vetor()
    pares = [(CARIMBO_6_PAGINAS, f"gs://b/{i}.pdf") for i in range(25)]
    gate, enviados, _ = _roda(pares, fetched={u: vetor for _t, u in pares})
    assert len(enviados) == V._MAX_PDFS_PER_CALL
    assert gate["n_enviados"] == V._MAX_PDFS_PER_CALL


def test_sem_gate_out_o_comportamento_e_o_de_antes():
    """`gate_out` é opcional — caller legado (o path de mov/day) não passa nada."""
    vetor = _pdf_vetor()
    enviados: list[bytes] = []

    async def _fake_fetch(urls):
        return [vetor]

    async def _fake_vision(provider, *, pdf_bytes_list, **kw):
        enviados.extend(pdf_bytes_list)
        return "OK"

    class _P:
        async def agenerate(self, **kw):
            return "TEXTO"

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(V, "fetch_pdfs_from_gcs", _fake_fetch)
        mp.setattr(V, "call_vision_l1", _fake_vision)
        mp.setenv("VISION_L1_ENABLED", "true")
        out = asyncio.run(V.call_l1_with_vision_fallback(
            _P(), model="m", prompt="p", response_schema=None,
            gcs_urls=["gs://b/p.pdf"],
            docs_text=[(CARIMBO_6_PAGINAS, "gs://b/p.pdf")],
        ))
    assert out == "OK" and len(enviados) == 1

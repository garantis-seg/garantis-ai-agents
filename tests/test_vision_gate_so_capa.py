"""A metade ai-agents da regra "peça identificada + extrator só alcançou a capa".

O caller (garantis-shared, 2ª passada da escada afirmativa do `fetch_peticao_doc`) já
sabe DUAS coisas que este repo não tem como saber: que documento é aquele — o título
diz `PETIÇÃO INICIAL` — e que o texto extraído é a CAPA dele, não o documento. O flag
`so_capa` do `DocGate` é o canal dessa informação.

🚨 SEM ISTO A REGRA É NO-OP, E O NO-OP MENTE. O cohort real tem 403-1.995 chars de
teor (medido em prod 2026-08-25): passa folgado no piso de 400 do
`texto_decide_sozinho`, o PDF nunca é baixado, o Vision nunca roda — e o card sai
escrito EM CIMA DA CAPA, afirmativo e falso. É exatamente o que o PR #1928 se recusou
a fazer quando deixou este cohort de fora de propósito.

⛔ Isto NÃO é "PDF textual vai pro Vision". Aquele benchmark (2026-05-28) mediu lift
ZERO e continua vetado. O que muda aqui é que o texto extraído não é o documento.
"""
from __future__ import annotations

import asyncio
import types

import pytest

pymupdf = pytest.importorskip("pymupdf")

from src.agents._utils import vision as V  # noqa: E402
from src.agents._utils.ocr_gate import (  # noqa: E402
    TEOR_MIN_CHARS,
    precisa_vision,
    texto_decide_sozinho,
)
from src.agents.mov_factsheet.schemas import DocGate  # noqa: E402

# A CAPA REAL: português limpo (rmgarbage ≈ 0), teor na faixa do meio. É o texto que
# derrota os 2 Sinais — e é por isso que o gate precisa da informação vinda de fora.
CAPA = ("PODER JUDICIARIO DO ESTADO DE SAO PAULO. Comarca de Sao Paulo. Foro das "
        "Execucoes Fiscais Estaduais. Processo Digital n. 1234567-89.2026.8.26.0100. "
        "Classe: Execucao Fiscal. Exequente: Fazenda Publica. ") * 3


def _pdf_texto() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_textbox(pymupdf.Rect(30, 40, 560, 780),
                        "EXCELENTISSIMO SENHOR DOUTOR JUIZ. " * 60,
                        fontsize=11, fontname="helv")
    return doc.tobytes()


# ── A PREMISSA: é o texto limpo que derrota os 2 Sinais ──────────────────────
def test_ANCORA_a_capa_decidiria_sozinha_e_o_PDF_nunca_desceria():
    """⛔ O teste que reprova o desenho SEM o flag. A capa não é lixo nem é curta —
    ela passa no piso, e o gate de página (o único que leria o PDF) fica inalcançável.
    É a MESMA classe do curto-circuito de 2026-08-10, com outro disfarce."""
    assert TEOR_MIN_CHARS <= len(CAPA) <= 2000, "premissa: a faixa do meio"
    assert texto_decide_sozinho(CAPA), "premissa: sem o flag o doc nem baixa"


def test_o_flag_e_ADITIVO_no_contrato():
    """Caller antigo / `documentos_anexados` seguem mandando par, sem `so_capa`."""
    assert DocGate(gcs_url="gs://b/x.pdf").so_capa is False
    assert DocGate(gcs_url="gs://b/x.pdf", so_capa=True).so_capa is True


# ── O gate por documento ─────────────────────────────────────────────────────
def test_precisa_vision_manda_a_capa_mesmo_com_PDF_DE_TEXTO_NATIVO():
    """⛔ MUTANTE: `so_capa` parar de furar o ramo "texto OK + PDF tem texto nativo".
    Este ramo é o certo pro caso geral — e é exatamente ele que mata o caso-alvo,
    porque o PDF da petição TEM texto (o extrator do provider é que só trouxe a capa).
    ⭐ O `motivo` é PRÓPRIO, não `0/N inalcancavel ()`: os 3 caminhos que mandam pro
    Vision têm que ser distinguíveis na telemetria."""
    pdf = _pdf_texto()
    assert precisa_vision(CAPA, pdf)[0] is False, "sem o flag: fica no texto"
    manda, info = precisa_vision(CAPA, pdf, so_capa=True)
    assert manda is True
    assert "peca-identificada-so-capa" in info["_nota"]["motivo"]


def test_so_capa_NAO_fura_os_fallbacks_NEGATIVOS():
    """⛔ MUTANTE: o flag virar "manda sempre". Fail-open não tem exceção — sem PDF e
    PDF ilegível (HTML/RTF servido como .pdf, 6 de 20 numa amostra do cohort)
    continuam ficando no texto, de graça."""
    assert precisa_vision(CAPA, None, so_capa=True)[0] is False
    assert precisa_vision(CAPA, b"<p>nao sou um PDF</p>", so_capa=True)[0] is False


# ── O fio inteiro, do par ao Gemini ──────────────────────────────────────────
def _roda(pares, pdf):
    enviados: list[bytes] = []

    async def _fake_fetch(urls):
        return [pdf]

    async def _fake_vision(provider, *, pdf_bytes_list, **kw):
        enviados.extend(pdf_bytes_list)
        return types.SimpleNamespace(metadata={"pdfs_processed": len(pdf_bytes_list)})

    class _P:
        async def agenerate(self, **kw):
            return "RESPOSTA_TEXTO"

    gate: dict = {}
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(V, "fetch_pdfs_from_gcs", _fake_fetch)
        mp.setattr(V, "call_vision_l1", _fake_vision)
        mp.setenv("VISION_L1_ENABLED", "true")
        asyncio.run(V.call_l1_with_vision_fallback(
            _P(), model="m", prompt="p", response_schema=None,
            gcs_urls=[p[1] for p in pares], docs_text=pares, gate_out=gate,
        ))
    return gate, enviados


def test_a_capa_com_flag_CHEGA_ao_Gemini_e_sem_flag_nao():
    """O fio: `so_capa` no par ⇒ o PDF sobe. Sem ele ⇒ `n_docs=1, n_enviados=0`, que
    é o estado de hoje (e o que o fail-open do shared lê pra NÃO gravar o card)."""
    pdf = _pdf_texto()
    gate, enviados = _roda([(CAPA, "gs://b/peticao.pdf", True)], pdf)
    assert len(enviados) == 1 and gate["n_enviados"] == 1
    assert gate["n_inalcancaveis"] == 1

    gate, enviados = _roda([(CAPA, "gs://b/peticao.pdf")], pdf)
    assert enviados == [] and gate == {"n_docs": 1, "n_inalcancaveis": 0,
                                       "n_enviados": 0, "n_nao_enviados_cap": 0,
                                       "motivo": None}


def test_par_de_2_elementos_continua_funcionando():
    """⛔ Mudar a aridade de `docs_text` quebraria o caller `day` e o fallback por
    `documentos_anexados` — os dois mandam par, e nenhum sabe o que é `so_capa`."""
    from src.agents.mov_factsheet.agent import classify_mov_factsheet  # noqa: F401
    gate, _ = _roda([("Trata-se de acao anulatoria. " * 30, "gs://b/x.pdf")],
                    _pdf_texto())
    assert gate["n_docs"] == 1, "o par de 2 atravessou o laço sem levantar"

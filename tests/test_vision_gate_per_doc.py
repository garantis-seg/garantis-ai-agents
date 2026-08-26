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
import types

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
        # carrega `metadata.pdfs_processed`: é dali que o veredito lê `n_enviados`.
        return types.SimpleNamespace(metadata={"pdfs_processed": len(pdf_bytes_list)})

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
    assert gate == {"n_docs": 2, "n_inalcancaveis": 1, "n_enviados": 1,
                    "n_nao_enviados_cap": 0, "motivo": "vetor"}


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


# ── 3. A FIAÇÃO: o agent tem que USAR o `documentos_gate`, não os anexados ────
# ⛔ Este bloco existe porque uma bateria de mutantes o pediu: fazer `gate_pairs`/
# `gate_urls` ignorarem o campo novo **sobrevivia a toda a suíte**. Os testes acima
# chamam `call_l1_with_vision_fallback` DIRETO, então a fiação de `agent.py` era
# território virgem — e é ela que decide se o gate vê o par certo.

def _classify(monkeypatch, *, documentos_anexados, documentos_gate, chunk=False,
              classe="peticao"):
    """Roda `classify_mov_factsheet` capturando o que chegou ao gate."""
    from src.agents.mov_factsheet import agent as A

    visto: dict = {}

    async def _fake_fallback(provider, **kw):
        visto.update(kw)
        if kw.get("gate_out") is not None:
            kw["gate_out"].update({"n_docs": 0, "n_inalcancaveis": 0,
                                   "n_enviados": 0, "motivo": None})

        class _R:
            text = '{"tipo_doc":"peticao_inicial","resumo_ato":"x"}'
            input_tokens = output_tokens = 1
            metadata = {"model_variant": "text"}
        return _R()

    monkeypatch.setattr(A, "call_l1_with_vision_fallback", _fake_fallback)
    monkeypatch.setattr(A, "create_provider", lambda p: object())
    monkeypatch.setenv("L1_NEUTRAL_ENABLED", "true")
    asyncio.run(A.classify_mov_factsheet(
        processo={"cnj": "10121509520268260224"},
        mov={"mov_id": "peticao-10121509520268260224", "texto": ""},
        documentos_anexados=documentos_anexados,
        documentos_gate=documentos_gate,
        classe=classe,
    ))
    return visto


# O payload REAL da petição: 1 entry concatenado, e o `gcs_url` dele é o do PRIMÁRIO
# (o AGRAVO). Se o agent usar ESTE, o gate julga o texto somado contra o PDF errado.
_ANEXADO_CONCATENADO = [{
    "doc_key": "jb-867158", "tipo": "1",
    "text_content": "AGRAVO DE INSTRUMENTO. Razoes recursais. " * 60,
    "gcs_url": "gs://b/agravo.pdf",
}]
_GATE_POR_DOC = [
    {"doc_key": "jb-867158", "text_content": "AGRAVO DE INSTRUMENTO. " * 60,
     "gcs_url": "gs://b/agravo.pdf"},
    {"doc_key": "jb-867195", "text_content": CARIMBO_6_PAGINAS,
     "gcs_url": "gs://b/peticao.pdf"},
]


def test_o_agent_roteia_o_gate_pelo_documentos_gate(monkeypatch):
    """⛔ MUTANTE: ignorar `gate_typed` reprova aqui — e o modo de falha real é mudo
    (cascade SUCCESS, card gravado, custo normal, PDF certo nunca enviado)."""
    visto = _classify(monkeypatch, documentos_anexados=_ANEXADO_CONCATENADO,
                      documentos_gate=_GATE_POR_DOC)
    assert visto["gcs_urls"] == ["gs://b/agravo.pdf", "gs://b/peticao.pdf"]
    # ⚠️ Trinca desde 2026-08-25 (`so_capa` no 3º elemento) — o ramo do
    # `documentos_gate` é o ÚNICO que sabe o flag. Ver `test_vision_gate_so_capa.py`.
    assert [p[0] for p in visto["docs_text"]] == [
        _GATE_POR_DOC[0]["text_content"], CARIMBO_6_PAGINAS,
    ]
    assert [p[2] for p in visto["docs_text"]] == [False, False], "default ADITIVO"


def test_sem_documentos_gate_o_agent_cai_nos_anexados(monkeypatch):
    """Compatibilidade: o path de MOV não manda o campo e não pode mudar de rota."""
    visto = _classify(monkeypatch, documentos_anexados=_ANEXADO_CONCATENADO,
                      documentos_gate=None)
    assert visto["gcs_urls"] == ["gs://b/agravo.pdf"]
    assert len(visto["docs_text"]) == 1


def test_o_CHUNKING_nao_pode_engolir_o_documentos_gate(monkeypatch):
    """🚨 Medido: 1.050 de 7.230 pns (14,5%) têm petição acima do CHUNK_SIZE de 180k
    e caem no caminho map-reduce — e há um cron dedicado a eles
    (`backfill-peticao-giants`). Ali o `documentos_anexados` NÃO carrega `gcs_url`
    no ramo de petição, então perder o campo deixa o gate com lista VAZIA: zero
    Vision, em silêncio. Só a 1ª variante leva os PDFs (basta uma call ver)."""
    from src.agents.mov_factsheet import agent as A

    gigante = [{"doc_key": "jb-1", "tipo": "1", "titulo": "PETICAO INICIAL",
                "text_content": "corpo da inicial. " * 12_000,   # > CHUNK_SIZE
                "gcs_url": None}]
    recebidos: list = []

    async def _fake_fallback(provider, **kw):
        recebidos.append(kw["gcs_urls"])

        class _R:
            text = '{"tipo_doc":"peticao_inicial","resumo_ato":"x"}'
            input_tokens = output_tokens = 1
            metadata = {"model_variant": "text"}
        return _R()

    monkeypatch.setattr(A, "call_l1_with_vision_fallback", _fake_fallback)
    monkeypatch.setattr(A, "create_provider", lambda p: object())
    monkeypatch.setenv("L1_NEUTRAL_ENABLED", "true")
    asyncio.run(A.classify_mov_factsheet(
        processo={"cnj": "10121509520268260224"},
        mov={"mov_id": "peticao-x", "texto": ""},
        documentos_anexados=gigante, documentos_gate=_GATE_POR_DOC, classe="peticao",
    ))
    assert len(recebidos) > 1, "premissa: a peça gigante foi chunkada"
    assert recebidos[0] == ["gs://b/agravo.pdf", "gs://b/peticao.pdf"]
    assert all(r == [] for r in recebidos[1:]), "só a 1ª variante paga o Vision"


def test_o_CHUNKING_devolve_o_VEREDITO_da_variante_0(monkeypatch):
    """⛔ MUTANTE: pegar o gate de qualquer variante (sem `v is variants[0]`) reprova
    aqui — só a 1ª recebe os PDFs, e as outras carimbam o dict ZERADO por cima. E
    o veredito tem que vir mesmo com o chunk 0 FALHANDO o parse: é justamente o
    chunk que viu o PDF que tem mais chance de vir grande e degenerar."""
    from src.agents.mov_factsheet import agent as A

    gigante = [{"doc_key": "jb-1", "tipo": "1", "titulo": "PETICAO INICIAL",
                "text_content": "corpo da inicial. " * 12_000,   # > CHUNK_SIZE
                "gcs_url": None}]
    _VEREDITO_V0 = {"n_docs": 2, "n_inalcancaveis": 1, "n_enviados": 0,
                    "n_nao_enviados_cap": 1, "motivo": "vetor"}

    async def _fake_fallback(provider, **kw):
        viu_pdf = bool(kw["gcs_urls"])
        if kw.get("gate_out") is not None:
            # o helper SEMPRE inicializa o dict — inclusive nas variantes sem PDF,
            # que é o que faz o mutante acima sobrescrever com zeros.
            kw["gate_out"].update(_VEREDITO_V0 if viu_pdf else {
                "n_docs": 0, "n_inalcancaveis": 0, "n_enviados": 0,
                "n_nao_enviados_cap": 0, "motivo": None})

        class _R:
            # a variante que viu o PDF degenera o JSON: o card dela é descartado
            # pelo reduce, e o veredito TEM que sobreviver a isso.
            text = "NAO EH JSON" if viu_pdf else (
                '{"tipo_doc":"peticao_inicial","resumo_ato":"x",'
                '"relevancia_merito":"media"}'
            )
            input_tokens = output_tokens = 1
            metadata = {"model_variant": "text"}
        return _R()

    monkeypatch.setattr(A, "call_l1_with_vision_fallback", _fake_fallback)
    monkeypatch.setattr(A, "create_provider", lambda p: object())
    monkeypatch.setenv("L1_NEUTRAL_ENABLED", "true")
    out = asyncio.run(A.classify_mov_factsheet(
        processo={"cnj": "10121509520268260224"},
        mov={"mov_id": "peticao-x", "texto": ""},
        documentos_anexados=gigante, documentos_gate=_GATE_POR_DOC, classe="peticao",
    ))

    assert out["card"].get("error") is None, "premissa: o reduce sobreviveu ao chunk ruim"
    assert out["vision_gate"] == _VEREDITO_V0


# ── 4. O STEERING dos anexos (v1.5) chega ao helper — e só onde deve ──────────
# O bloco existe pelo mesmo motivo do bloco 3: `call_l1_with_vision_fallback` é
# testado direto no `test_peticao_steering_anexos.py`, então a FIAÇÃO de `agent.py`
# ficaria descoberta — e é ela que decide se o fix chega a existir em prod.

def test_o_agent_monta_o_prompt_com_steering_quando_ha_candidato(monkeypatch):
    """⛔ MUTANTE: não passar `prompt_vision` reprova aqui. Sem ele o ramo Vision
    manda o prompt de texto, a chamada sai igual, custa igual, e o fix é inerte."""
    visto = _classify(monkeypatch, documentos_anexados=_ANEXADO_CONCATENADO,
                      documentos_gate=_GATE_POR_DOC)
    assert "PDF ANEXADOS" in (visto["prompt_vision"] or "")
    assert "PDF ANEXADOS" not in visto["prompt"], (
        "o prompt do caminho TEXTO não pode declarar anexo")


def test_sem_candidato_de_pdf_nao_ha_prompt_de_vision(monkeypatch):
    """Nenhum doc com `gcs_url` ⇒ o ramo Vision é inalcançável. Montar a 2ª versão
    ali seria trabalho morto — e, pior, um segundo prompt em `llm_raw_prompt` que
    nunca foi enviado."""
    sem_pdf = [{"doc_key": "jb-1", "text_content": "corpo da inicial. " * 50,
                "gcs_url": None}]
    visto = _classify(monkeypatch, documentos_anexados=sem_pdf, documentos_gate=sem_pdf)
    assert visto["prompt_vision"] is None


def test_a_lane_MOV_nao_recebe_prompt_de_vision(monkeypatch):
    """O steering fala de "partes da PETIÇÃO INICIAL" e a lane mov manda 1 doc por
    entry — lá o texto do prompt JÁ é o do doc cujo PDF subiu. Vazar pra ela seria
    mudar 1,46% das chamadas de mov sem eval que as cubra."""
    visto = _classify(monkeypatch, documentos_anexados=_ANEXADO_CONCATENADO,
                      documentos_gate=_GATE_POR_DOC, classe=None)
    assert visto["prompt_vision"] is None

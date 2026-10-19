"""O PDF acima do cap inline sobe em LOTES de páginas, 1 chamada Vision por lote, e o card
junta os lotes pelo redutor da peça grande. O PDF abaixo do cap segue igual, byte a byte.

Os PDFs são scans de verdade (1 imagem incompressível por página), com o nº da página no
texto: é por ele que o teste confere QUAIS páginas cada lote leva, e não só quantas.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import re

import pytest

pymupdf = pytest.importorskip("pymupdf")

from google.genai import types as gtypes  # noqa: E402
from pypdf import PdfReader  # noqa: E402

from src.agents._utils import vision as V  # noqa: E402
from src.agents._utils.ocr_gate import lotes_de_paginas  # noqa: E402
from src.providers.base import BaseLLMProvider  # noqa: E402


def _scan(pesos: list[int], marca: str = "PAGINA") -> bytes:
    doc = pymupdf.open()
    for i, peso in enumerate(pesos, 1):
        pg = doc.new_page()
        lado = int((peso / 3) ** 0.5)
        pix = pymupdf.Pixmap(pymupdf.csRGB, lado, lado, os.urandom(lado * lado * 3), False)
        pg.insert_image(pg.rect, pixmap=pix)
        pg.insert_text((20, 20), f"{marca}-{i}")
    return doc.tobytes()


def _paginas(pdf: bytes) -> list[int]:
    return [int(re.search(r"PAGINA-(\d+)", p.extract_text()).group(1))
            for p in PdfReader(io.BytesIO(pdf)).pages]


# ── 1. O corte em lotes ──────────────────────────────────────────────────────
def test_os_lotes_cabem_no_cap_e_levam_todas_as_paginas_na_ordem():
    pdf = _scan([20_000] * 6)
    cap = 50_000

    lotes = lotes_de_paginas(pdf, cap)

    assert len(lotes) == -(-len(pdf) // cap), "o menor nº de lotes que o tamanho permite"
    assert all(len(lote) <= cap for lote in lotes)
    assert [p for lote in lotes for p in _paginas(lote)] == [1, 2, 3, 4, 5, 6]


def test_o_lote_com_pagina_pesada_se_divide_ate_caber():
    """⛔ MUTANTE: sem a divisão ao meio, o 1º lote (páginas 1-3, com a página de 60 KB)
    passa do cap, e a chamada dele falharia pelo cap."""
    pdf = _scan([10_000, 10_000, 60_000, 10_000, 10_000, 10_000])
    cap = 70_000

    lotes = lotes_de_paginas(pdf, cap)

    assert all(len(lote) <= cap for lote in lotes)
    assert [p for lote in lotes for p in _paginas(lote)] == [1, 2, 3, 4, 5, 6]


def test_pagina_sozinha_acima_do_cap_sai_sozinha():
    """Nenhuma chamada lê esta página. Ela sai como lote próprio, e o helper a vê, em vez
    de ela sumir."""
    lotes = lotes_de_paginas(_scan([10_000, 80_000]), 50_000)

    assert [_paginas(lote) for lote in lotes] == [[1], [2]]
    assert len(lotes[1]) > 50_000


# ── 2. O helper ──────────────────────────────────────────────────────────────
class _ErroDaAPI(RuntimeError):
    """O `__str__` do `google.genai.errors.APIError` começa pelo código (ver o formato
    preso em `test_vision_inline_cap.py`)."""

    def __init__(self) -> None:
        super().__init__("400 INVALID_ARGUMENT. {'error': {'code': 400}}")


class _Provider:
    """Client fake que guarda (contents, config) de cada chamada. `falha(texto)` diz se a
    chamada com aquele prompt levanta. Com `eco`, a resposta repete o prompt da chamada."""

    def __init__(self, falha=lambda texto: False, eco: bool = False) -> None:
        self._types = gtypes
        self.chamadas: list[tuple[list, object]] = []
        self.textos: list[str] = []
        outer = self

        class _Models:
            async def generate_content(self, *, model, contents, config):
                outer.chamadas.append((contents, config))
                if falha(contents[-1].text):
                    raise _ErroDaAPI()

                class _R:
                    text = contents[-1].text if eco else "{}"
                    usage_metadata = None

                return _R()

        class _Aio:
            models = _Models()

        class _Client:
            aio = _Aio()

        self._client = _Client()

    def get_model_pricing(self, model):
        return {"input_per_1m": 0.0, "output_per_1m": 0.0}

    calculate_cost = BaseLLMProvider.calculate_cost

    async def agenerate(self, **kw):
        self.textos.append(kw["prompt"])
        return "RESPOSTA_TEXTO"


def _roda(prov, pdfs, *, lotes_out, gate=True, monkeypatch=None, prompt_vision=None):
    """`call_l1_with_vision_fallback` com o GCS fake. `gate=True` passa pelo gate de
    OCR, como em produção (o texto vazio é texto-lixo, então o PDF sobe)."""
    urls = [f"gs://b/{i}.pdf" for i in range(len(pdfs))]
    por_url = dict(zip(urls, pdfs))

    async def _fake_fetch(pedidos):
        return [por_url[u] for u in pedidos]

    gate_out: dict = {}
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(V, "fetch_pdfs_from_gcs", _fake_fetch)
        mp.setenv("VISION_L1_ENABLED", "true")
        out = asyncio.run(V.call_l1_with_vision_fallback(
            prov, model="m", prompt="PROMPT", response_schema=None, gcs_urls=urls,
            docs_text=[("", u) for u in urls] if gate else None,
            gate_out=gate_out, lotes_out=lotes_out, seed=7, prompt_vision=prompt_vision,
        ))
    return out, gate_out


def _dump(prov):
    return [([p.model_dump() for p in contents], config.model_dump())
            for contents, config in prov.chamadas]


@pytest.mark.parametrize("tamanho", [1024 * 1024, V._INLINE_TOTAL_BYTES_CAP])
def test_o_PDF_abaixo_do_cap_sobe_IGUAL_byte_a_byte(tamanho):
    """O caso de quase todo o volume. Com e sem `lotes_out`, a chamada ao Gemini tem os
    mesmos bytes, o mesmo prompt e o mesmo config, e o veredito é o mesmo.
    ⛔ MUTANTE: `>` vira `>=` no corte do modo lotes. O PDF exatamente no cap passa a subir
    em lotes, e a chamada muda."""
    pdf = b"0" * tamanho
    sem, com = _Provider(), _Provider()
    lotes: list = []

    out_sem, gate_sem = _roda(sem, [pdf], lotes_out=None, gate=False)
    out_com, gate_com = _roda(com, [pdf], lotes_out=lotes, gate=False)

    assert len(com.chamadas) == 1
    assert _dump(com) == _dump(sem)
    assert gate_com == gate_sem
    assert lotes == [], "sem PDF acima do cap, o helper não fala de lotes"
    assert out_com.metadata == out_sem.metadata


def _lote_de(contents) -> tuple[int, int] | None:
    m = re.match(r"\[PARTE (\d+)/(\d+) ", contents[-1].text)
    return (int(m.group(1)), int(m.group(2))) if m else None


def test_o_PDF_acima_do_cap_sobe_em_lotes_1_chamada_por_lote(monkeypatch):
    monkeypatch.setattr(V, "_INLINE_TOTAL_BYTES_CAP", 50_000)
    pdf = _scan([20_000] * 6)
    prov = _Provider()
    lotes: list = []

    out, gate = _roda(prov, [pdf], lotes_out=lotes)

    pelo_lote = sorted(prov.chamadas, key=lambda c: _lote_de(c[0]))
    assert [_lote_de(c) for c, _cfg in pelo_lote] == [(1, 3), (2, 3), (3, 3)]
    pdfs = [c[0].inline_data.data for c, _cfg in pelo_lote]
    assert all(len(b) <= 50_000 for b in pdfs)
    assert [p for b in pdfs for p in _paginas(b)] == [1, 2, 3, 4, 5, 6]
    assert all(c[-1].text.endswith("\n\nPROMPT") for c, _cfg in prov.chamadas), (
        "cada lote leva o prompt inteiro, com a parte dita antes dele")
    assert len(lotes) == 3 and out is lotes[0]
    assert gate == {"n_docs": 1, "n_inalcancaveis": 1, "n_enviados": 1,
                    "n_nao_enviados_cap": 0, "motivo": "imagem",
                    "n_lotes": 3, "n_lotes_falha": 0}
    assert prov.textos == [], "o PDF foi lido: o card não cai no texto"


def test_sem_lotes_out_o_PDF_acima_do_cap_segue_de_fora(monkeypatch):
    """Caller que não junta cards não recebe lotes: o PDF fica de fora, como sempre."""
    monkeypatch.setattr(V, "_INLINE_TOTAL_BYTES_CAP", 50_000)
    prov = _Provider()

    out, gate = _roda(prov, [_scan([20_000] * 6)], lotes_out=None)

    assert prov.chamadas == [] and out == "RESPOSTA_TEXTO"
    assert gate["n_nao_enviados_cap"] == 1 and "n_lotes" not in gate


def test_lote_que_falha_conta_e_o_PDF_lido_em_parte_NAO_conta_como_enviado(monkeypatch):
    """⛔ MUTANTE: contar como enviado o PDF que teve 1 lote recusado. A régua do CEGO
    (`n_inalcancaveis > n_enviados`) deixaria de ver o PDF lido pela metade."""
    monkeypatch.setattr(V, "_INLINE_TOTAL_BYTES_CAP", 50_000)
    prov = _Provider(falha=lambda texto: texto.startswith("[PARTE 2/3 "))
    lotes: list = []

    out, gate = _roda(prov, [_scan([20_000] * 6)], lotes_out=lotes)

    assert len(prov.chamadas) == 3 and len(lotes) == 2 and out is lotes[0]
    assert gate["n_lotes"] == 3 and gate["n_lotes_falha"] == 1
    assert gate["n_enviados"] == 0
    assert gate["n_nao_enviados_cap"] == 0, "o PDF se partiu inteiro: o lote falhou, não o cap"
    assert "n_falha_vision" not in gate, "o card leu 2 lotes: ele não cai no texto"
    assert prov.textos == []


def test_todos_os_lotes_falham_e_o_card_cai_no_texto_com_o_veredito(monkeypatch):
    """A mesma saída da chamada única que falha: texto, `n_falha_vision` e o erro no
    formato `<Classe>: <código>` que a tela lê."""
    monkeypatch.setattr(V, "_INLINE_TOTAL_BYTES_CAP", 50_000)
    prov = _Provider(falha=lambda texto: True)
    lotes: list = []

    out, gate = _roda(prov, [_scan([20_000] * 6)], lotes_out=lotes)

    assert out == "RESPOSTA_TEXTO" and prov.textos == ["PROMPT"]
    assert lotes == []
    assert gate["n_lotes"] == 3 and gate["n_lotes_falha"] == 3
    assert gate["n_enviados"] == 0 and gate["n_falha_vision"] == 1
    assert re.match(r"^\w+: \d{3}\b", gate["erro_vision"])


def test_pagina_que_nem_sozinha_cabe_deixa_o_PDF_no_contador_do_cap(monkeypatch):
    """A tela do upload lê `n_nao_enviados_cap > 0` como "mande um arquivo menor", e
    qualquer outra falha como "tente de novo". Repetir não faz a página caber.
    ⛔ MUTANTE: chamar também o lote que não cabe. Ele levanta pelo cap, vira lote que
    falhou, e o PDF sai do contador do cap."""
    monkeypatch.setattr(V, "_INLINE_TOTAL_BYTES_CAP", 50_000)
    prov = _Provider()
    lotes: list = []

    _out, gate = _roda(prov, [_scan([10_000, 80_000, 10_000])], lotes_out=lotes)

    assert [_paginas(c[0].inline_data.data) for c, _cfg in prov.chamadas] == [[1], [3]]
    assert gate["n_lotes"] == 2 and gate["n_lotes_falha"] == 0
    assert gate["n_nao_enviados_cap"] == 1 and gate["n_enviados"] == 0


def test_os_PDFs_que_cabem_sobem_com_a_MESMA_selecao_de_hoje(monkeypatch):
    """[grande, anexo de 30 KB, anexo de 10 KB], com teto por PDF de 20 KB. Hoje o 1º
    passa do total e sai, o 2º passa do teto por PDF e sai, e sobe só o 3º. Com os lotes,
    a chamada do que cabe tem de ser a mesma.
    ⛔ MUTANTE: montar essa chamada com a lista sem o grande. O anexo de 30 KB vira o 1º,
    fica isento do teto por PDF e sobe junto."""
    monkeypatch.setattr(V, "_INLINE_TOTAL_BYTES_CAP", 50_000)
    monkeypatch.setattr(V, "_INLINE_PER_PDF_BYTES_CAP", 20_000)
    grande, anexo_30, anexo_10 = _scan([20_000] * 6), b"A" * 30_000, b"B" * 10_000
    prov = _Provider()
    lotes: list = []

    _out, gate = _roda(prov, [grande, anexo_30, anexo_10], lotes_out=lotes, gate=False)

    sem_lote = [c for c, _cfg in prov.chamadas if _lote_de(c) is None]
    assert [[p.inline_data.data for p in c[:-1]] for c in sem_lote] == [[anexo_10]]
    assert sem_lote[0][-1].text == "PROMPT", "a chamada do que cabe é a de sempre"
    assert len(prov.chamadas) == 4 and len(lotes) == 4
    assert gate["n_lotes"] == 4 and gate["n_lotes_falha"] == 0
    assert gate["n_enviados"] == 2, "o anexo de 10 KB e o grande, lido inteiro"
    assert gate["n_nao_enviados_cap"] == 1, "o anexo de 30 KB, como hoje"


@pytest.mark.parametrize("grande_na_frente", [True, False])
def test_os_cards_seguem_a_ordem_dos_PDFs(monkeypatch, grande_na_frente):
    """O redutor junta os cards na ordem de `lotes_out`, e o valor declarado por último
    vence. A ordem é a do último PDF de cada chamada na lista do caller.
    ⛔ MUTANTE: a chamada do que cabe sempre na frente (ou sempre no fim). Um dos 2 casos
    põe o anexo do lado errado dos lotes."""
    monkeypatch.setattr(V, "_INLINE_TOTAL_BYTES_CAP", 50_000)
    grande, anexo = _scan([20_000] * 6), b"B" * 10_000
    prov = _Provider(eco=True)
    lotes: list = []

    _roda(prov, [grande, anexo] if grande_na_frente else [anexo, grande],
          lotes_out=lotes, gate=False)

    partes = ["[PARTE 1/3", "[PARTE 2/3", "[PARTE 3/3"]
    esperado = partes + ["PROMPT"] if grande_na_frente else ["PROMPT"] + partes
    assert [r.text.split(" do PDF")[0] if r.text.startswith("[PARTE") else r.text
            for r in lotes] == esperado


def test_o_PDF_que_o_pypdf_nao_parte_fica_no_cap_e_o_resto_sobe(monkeypatch):
    """⛔ MUTANTE: a falha do corte sobe e derruba também a chamada do que cabe."""
    monkeypatch.setattr(V, "_INLINE_TOTAL_BYTES_CAP", 50_000)
    from src.agents._utils import ocr_gate

    def _explode(pdf, cap):
        raise ValueError("pypdf não abriu")

    monkeypatch.setattr(ocr_gate, "lotes_de_paginas", _explode)
    anexo = b"B" * 10_000
    prov = _Provider()
    lotes: list = []

    _out, gate = _roda(prov, [_scan([20_000] * 6), anexo], lotes_out=lotes, gate=False)

    assert [[p.inline_data.data for p in c[:-1]] for c, _cfg in prov.chamadas] == [[anexo]]
    assert gate["n_enviados"] == 1 and gate["n_nao_enviados_cap"] == 1


def test_nada_cabe_e_nada_se_parte_o_cap_conta_e_o_card_cai_no_texto(monkeypatch):
    """1 PDF de 1 página acima do cap: nenhum lote cabe. A chamada única levanta o erro do
    cap, que conta no `n_nao_enviados_cap`.
    ⛔ MUTANTE: levantar sem passar pelo contador do cap."""
    monkeypatch.setattr(V, "_INLINE_TOTAL_BYTES_CAP", 50_000)
    prov = _Provider()
    lotes: list = []

    out, gate = _roda(prov, [_scan([80_000])], lotes_out=lotes, gate=False)

    assert prov.chamadas == [] and lotes == []
    assert out == "RESPOSTA_TEXTO" and prov.textos == ["PROMPT"]
    assert gate["n_nao_enviados_cap"] == 1


def test_os_lotes_levam_o_prompt_do_ramo_vision(monkeypatch):
    """⛔ MUTANTE: os lotes recebem o `prompt` de texto no lugar do `prompt_vision`."""
    monkeypatch.setattr(V, "_INLINE_TOTAL_BYTES_CAP", 50_000)
    prov = _Provider()

    _roda(prov, [_scan([20_000] * 6)], lotes_out=[], prompt_vision="PV")

    assert len(prov.chamadas) == 3
    assert all(c[-1].text.endswith("\n\nPV") for c, _cfg in prov.chamadas)


# ── 3. O agent junta os lotes ────────────────────────────────────────────────
def _classify_com_lotes(monkeypatch, textos: list[str], *, classe=None,
                        falha_http: int = 0) -> dict:
    """`classify_mov_factsheet` com um helper fake que lê o PDF em len(textos) lotes.
    `falha_http` é o nº de lotes que o helper já contou como falha."""
    from src.agents.mov_factsheet import agent as A

    def _r(texto):
        class _R:
            text = texto
            input_tokens = output_tokens = 10
            cached_tokens = 0
            metadata = {"model_variant": "vision", "cost_usd": 0.001, "pdfs_processed": 1}
        return _R()

    async def _fake_fallback(provider, **kw):
        respostas = [_r(t) for t in textos]
        if kw.get("lotes_out") is not None:
            kw["lotes_out"].extend(respostas)
            kw["gate_out"].update({"n_docs": 1, "n_inalcancaveis": 1, "n_enviados": 1,
                                   "n_nao_enviados_cap": 0, "motivo": "texto-lixo",
                                   "n_lotes": len(textos) + falha_http,
                                   "n_lotes_falha": falha_http})
        return respostas[0]

    monkeypatch.setattr(A, "call_l1_with_vision_fallback", _fake_fallback)
    monkeypatch.setattr(A, "create_provider", lambda p: object())
    monkeypatch.setenv("L1_NEUTRAL_ENABLED", "true")
    return asyncio.run(A.classify_mov_factsheet(
        processo={"cnj": "00000000000000000000"},
        mov={"mov_id": "m-1", "texto": "Juntada de documento"},
        documentos_anexados=[{"doc_key": "d1", "tipo": "1", "text_content": "",
                              "gcs_url": "gs://b/scan.pdf"}],
        classe=classe,
    ))


_LOTE_1 = '{"tipo_doc":"outros","relevancia_merito":"baixa","resumo_ato":"Capa dos autos."}'
_LOTE_2 = ('{"tipo_doc":"sentenca","relevancia_merito":"alta","resumo_ato":"Julga procedente.",'
           '"decisao":{"tem_decisao":true,"natureza":"procedente",'
           '"dispositivo":"JULGO PROCEDENTE o pedido"}}')


def test_o_agent_junta_os_cards_dos_lotes_pelo_redutor_da_peca_grande(monkeypatch):
    """⛔ MUTANTE: não juntar os lotes (ler só a resposta devolvida). O card sai da capa
    (lote 1) e a sentença do lote 2 some."""
    out = _classify_com_lotes(monkeypatch, [_LOTE_1, _LOTE_2])

    card = out["card"]
    assert card["tipo_doc"] == "sentenca" and card["relevancia_merito"] == "alta"
    assert card["decisao"]["natureza"] == "procedente"
    assert card["resumo_ato"] == "Capa dos autos. Julga procedente."
    assert card["mov_id"] == "m-1"
    assert out["usage"]["input_tokens"] == 20 and out["usage"]["model_variant"] == "vision"
    assert out["vision_gate"]["n_lotes"] == 2 and out["vision_gate"]["n_lotes_falha"] == 0
    assert out["raw_response"] == "[lotes:2/2 partes]"


def test_o_lote_cujo_card_nao_parseia_conta_como_falha(monkeypatch):
    """O PDF lido em parte sai do `n_enviados`, como na falha HTTP, e a régua do CEGO o vê.
    ⛔ MUTANTE: o agent sobrescreve o `n_lotes_falha` do helper (`=` no lugar de `+=`), ou
    deixa o PDF no `n_enviados`."""
    out = _classify_com_lotes(monkeypatch, [_LOTE_1, "NAO EH JSON", _LOTE_2], falha_http=1)

    assert out["card"]["tipo_doc"] == "sentenca", "o reduce segue com os lotes bons"
    assert out["vision_gate"]["n_lotes"] == 4 and out["vision_gate"]["n_lotes_falha"] == 2
    assert out["vision_gate"]["n_enviados"] == 0


_PETICAO_1 = ('{"tipo_doc":"peticao_inicial","relevancia_merito":"alta","resumo_ato":"Inicial.",'
              '"cdas":[{"numero":"80.6.19.000001-01"}]}')
_PETICAO_2 = ('{"tipo_doc":"peticao_inicial","relevancia_merito":"alta",'
              '"resumo_ato":"Fim da inicial.",'
              '"processos_citados":[{"cnj":"0000134-19.2004.4.02.5101","papel":"originario"}],'
              '"valor_causa_declarado":12345.6,"valor_causa_evidencia":"Da-se a causa o valor"}')


def test_o_ramo_peticao_junta_os_lotes_com_o_schema_da_peticao(monkeypatch):
    """⛔ MUTANTE: o lote vira card sem a `classe`. O card perde as CDAs, os processos
    citados e o valor da causa, que só o schema da petição tem."""
    card = _classify_com_lotes(monkeypatch, [_PETICAO_1, _PETICAO_2], classe="peticao")["card"]

    assert [c["numero"] for c in card.get("cdas") or []] == ["80.6.19.000001-01"]
    assert [p["cnj"] for p in card.get("processos_citados") or []] == ["0000134-19.2004.4.02.5101"]
    assert card.get("valor_causa_declarado") == 12345.6


def test_a_emenda_que_cabe_vence_a_inicial_lida_em_lotes(monkeypatch):
    """O caminho real (gate, helper, agent e redutor), com o Gemini fake respondendo pelo
    PDF que recebeu. A inicial escaneada passa do cap e declara R$ 1 mi. A emenda, depois
    dela na lista do materializer, cabe e corrige para R$ 2 mi."""
    from src.agents.mov_factsheet import agent as A

    monkeypatch.setattr(V, "_INLINE_TOTAL_BYTES_CAP", 50_000)
    monkeypatch.setattr(V, "_INLINE_PER_PDF_BYTES_CAP", 20_000)
    inicial, emenda = _scan([20_000] * 6), _scan([10_000], marca="EMENDA")
    por_url = {"gs://b/inicial.pdf": inicial, "gs://b/emenda.pdf": emenda}

    def _card(valor=None):
        c = {"tipo_doc": "peticao_inicial", "relevancia_merito": "alta", "resumo_ato": "x"}
        if valor:
            c |= {"valor_causa_declarado": valor, "valor_causa_evidencia": f"R$ {valor}"}
        return json.dumps(c)

    class _Models:
        async def generate_content(self, *, model, contents, config):
            # o gate reescreve o PDF: o fake reconhece cada peça pelo texto da página
            texto = " ".join(pg.extract_text() for p in contents[:-1]
                             for pg in PdfReader(io.BytesIO(p.inline_data.data)).pages)

            class _R:
                text = (_card(2_000_000.0) if "EMENDA" in texto
                        else _card(1_000_000.0) if "PAGINA-6" in texto else _card())
                usage_metadata = None
            return _R()

    class _Prov(_Provider):
        def __init__(self):
            super().__init__()
            self._client.aio.models = _Models()

    async def _fetch(urls):
        return [por_url[u] for u in urls]

    monkeypatch.setattr(V, "fetch_pdfs_from_gcs", _fetch)
    monkeypatch.setattr(A, "create_provider", lambda p: _Prov())
    monkeypatch.setenv("VISION_L1_ENABLED", "true")
    monkeypatch.setenv("L1_NEUTRAL_ENABLED", "true")

    out = asyncio.run(A.classify_mov_factsheet(
        processo={"cnj": "00000000000000000000"},
        mov={"mov_id": "peticao-x", "texto": "Peticao inicial"},
        documentos_anexados=[{"doc_key": "conjunto", "text_content": "(capa)"}],
        documentos_gate=[{"text_content": "", "gcs_url": "gs://b/inicial.pdf"},
                         {"text_content": "", "gcs_url": "gs://b/emenda.pdf"}],
        classe="peticao",
    ))

    assert out["card"]["valor_causa_declarado"] == 2_000_000.0
    assert out["vision_gate"]["n_lotes"] == 4 and out["vision_gate"]["n_lotes_falha"] == 0


def test_com_1_resposta_o_agent_segue_o_caminho_de_sempre(monkeypatch):
    out = _classify_com_lotes(monkeypatch, [_LOTE_2])

    assert out["card"]["tipo_doc"] == "sentenca"
    assert out["raw_response"] == _LOTE_2, "sem redutor: a resposta crua é a do modelo"

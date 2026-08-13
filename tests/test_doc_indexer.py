"""O indexador: nativo puro sem OCR, misto com o gate acusando as páginas certas,
determinismo do hash de saída, e as mutações que TÊM que quebrar.

Camada 1 da pesquisa (Layer-Isolated Evaluation, arXiv:2606.11686): **todo o
scaffold testado SEM chamar modelo nenhum.** Rápido, 100% determinístico,
não-flaky. O único ponto de LLM do pipeline (`ocr_paginas`) é dublado — e o
dublê é o que permite afirmar "zero OCR" em vez de esperar que não aconteça:
num PDF nativo o dublê registra 0 chamadas, e o teste falha se registrar 1.

Os PDFs são **sintéticos**, construídos com PyMuPDF na hora, pelo mesmo motivo
que `test_vision_gate_per_doc.py` já faz: fixture binária no repo não diz por
que ela aciona o gate, e quando o threshold muda ninguém sabe se a fixture ainda
é o caso que se queria testar. Aqui a página-vetor é vetor por construção (900
paths + só o carimbo do ESAJ), e isso está escrito no código que a produz.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json

import pytest

pymupdf = pytest.importorskip("pymupdf")

from src.agents.doc_indexer import agent as A  # noqa: E402
from src.agents.doc_indexer import extracao, gate  # noqa: E402
from src.agents.doc_indexer import ocr as O  # noqa: E402
from src.agents.doc_indexer.schemas import IndexarRequest  # noqa: E402

# ── o texto das fixtures ─────────────────────────────────────────────────────

#: O carimbo do ESAJ: português impecável, `garbage_ratio` ≈ 0 e a peça presa na
#: imagem. É o caso que derrota o Sinal 2 sozinho — 8.597 documentos assim em
#: prod (medido 2026-08-10) — e a razão de o gate por página perguntar as duas
#: coisas.
CARIMBO = (
    "Para conferir o original, acesse o site https://esaj.tjsp.jus.br/pastadigital/"
    "pg/abrirConferenciaDocumento.do, informe o processo 1012150-95.2026.8.26.0224 "
    "e codigo l4Q1NmsN.\nEste documento e copia do original, assinado digitalmente "
    "por ANGELO BUENO PASCHOINI.\nfls. {n}"
)

#: As duas armadilhas de segmentação do §1.5, no mesmo parágrafo de propósito:
#: `art. 142` (abreviação jurídica) e `R$ 723.810.827,57` (pontos entre dígitos).
#: Se qualquer uma quebrar sentença, o valor deixa de ser citável como unidade.
TEXTO_ACORDAO = (
    "Fica mantida a exigencia de IRPJ no valor de R$ 723.810.827,57. "
    "Nos termos do art. 142 do CTN, o lancamento e atividade vinculada. "
    "Recurso voluntario conhecido e parcialmente provido, nos termos do voto."
)


def _pagina_texto(doc, texto: str) -> None:
    p = doc.new_page()
    p.insert_textbox(
        pymupdf.Rect(40, 60, 550, 760), texto, fontsize=10, fontname="helv"
    )


def _pagina_vetor(doc, n: int) -> None:
    """Página cujo corpo virou CURVAS: 900 paths e só o carimbo como texto.

    `get_images()` não vê nada (não é raster) e o texto é limpo — ela passava
    por born-digital antes do ramo de vetor do gate (2026-08-12, caso Steel).
    """
    p = doc.new_page()
    for i in range(900):
        p.draw_line(
            pymupdf.Point(30, 20 + (i % 700)), pymupdf.Point(40 + (i % 300), 20 + (i % 700))
        )
    p.insert_textbox(
        pymupdf.Rect(30, 40, 560, 90), CARIMBO.format(n=n), fontsize=6, fontname="helv"
    )


def pdf_nativo_puro(n_paginas: int = 2) -> bytes:
    doc = pymupdf.open()
    for _ in range(n_paginas):
        _pagina_texto(doc, TEXTO_ACORDAO + " " + "Consideracoes do relator. " * 20)
    return doc.tobytes()


def pdf_misto() -> bytes:
    """4 folhas: nativa, VETOR, VAZIA, nativa. O gate tem que acusar 2 e 3."""
    doc = pymupdf.open()
    _pagina_texto(doc, TEXTO_ACORDAO + " " + "Relatorio do processo. " * 20)
    _pagina_vetor(doc, 2)
    doc.new_page()  # em branco: nem texto, nem imagem, nem path
    _pagina_texto(doc, "Recurso voluntario conhecido e provido. " * 30)
    return doc.tobytes()


# ── dublê do único ponto de LLM ──────────────────────────────────────────────

class OcrDuble:
    """Substitui `ocr_paginas`. Registra as chamadas e devolve texto plausível.

    Registrar é o ponto: "zero OCR" vira uma asserção sobre `self.chamadas`, não
    uma esperança. E o texto devolvido é diferente do nativo de propósito — é
    como o teste de mistura prova que a página OCR foi COSTURADA no lugar da
    nativa, e não somada a ela.
    """

    def __init__(self, textos: dict[int, str] | None = None, custo: float = 0.0031):
        self.textos = textos or {}
        self.custo = custo
        self.chamadas: list[list[int]] = []

    async def __call__(self, provider, pdf_bytes, paginas, *, model=None):
        self.chamadas.append(sorted(paginas))
        entregues = {
            p: self.textos.get(p, f"Texto recuperado por OCR da folha {p}. "
                                  "Multa de oficio de R$ 100.000,00 aplicada.")
            for p in sorted(paginas)
        }
        return entregues, {
            "model": "gemini-3.1-flash-lite", "cost_usd": self.custo,
            "paginas_pedidas": len(paginas), "paginas_lidas": len(entregues),
            "prompt_version": O.PROMPT_VERSION, "erro": None,
        }


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    """A flag é OFF por default (ship inerte). Todo teste de comportamento a liga
    explicitamente; o teste do ship inerte a desliga de novo."""
    monkeypatch.setenv(A.FLAG_DOC_INDEXER, "true")


def _indexar(pdf: bytes, duble: OcrDuble, monkeypatch, **kw):
    monkeypatch.setattr(A, "ocr_paginas", duble)
    monkeypatch.setattr(A, "_provider", lambda nome: object())
    req = IndexarRequest(
        doc_id=kw.pop("doc_id", "carf:raw/carf/1350272.pdf"),
        pdf_base64=base64.b64encode(pdf).decode(),
        **kw,
    )
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
        A.indexar(req)
    )


# ═════════════════════════════════════════════════════════════════════════════
# 1. PDF NATIVO PURO — zero OCR
# ═════════════════════════════════════════════════════════════════════════════

def test_pdf_nativo_puro_nao_chama_ocr_nenhuma_vez(monkeypatch):
    """A economia inteira da onda: OCR é ∝ páginas inalcançáveis, não ao acervo.

    Se este teste quebrar, todo documento born-digital do acervo passa a pagar
    Gemini — e o pipeline deixa de ser "código determinístico + no máximo 1
    chamada de OCR" para virar um OCR com cara de pipeline.
    """
    duble = OcrDuble()
    r = _indexar(pdf_nativo_puro(), duble, monkeypatch)

    assert r.success, r.error
    assert duble.chamadas == [], "PDF nativo NÃO pode acionar o OCR"
    assert r.paginas_ocr == []
    assert r.custo == 0.0 and r.cost_usd == 0.0


def test_pdf_nativo_declara_metodo_native_e_extractor_do_pymupdf(monkeypatch):
    """`metodo` e `extractor_version` são o que diz ao humano contra o que a
    citação vale. Nativo ⇒ contra o PDF real."""
    r = _indexar(pdf_nativo_puro(), OcrDuble(), monkeypatch)
    d = r.documento_indexado

    assert r.metodo == "native"
    assert d["extractor_version"].startswith("pymupdf-")
    assert d["extractor_version"].endswith(f"+{extracao.NORM_VERSION}")
    assert "ocr" not in d["extractor_version"]


def test_extractor_version_da_pagina_registra_o_metodo_usado(monkeypatch):
    """Requisito literal do desenho: *"por página: método usado (native|ocr)
    registrado no DocumentoIndexado/âncora (extractor_version inclui o método)"*."""
    r = _indexar(pdf_nativo_puro(), OcrDuble(), monkeypatch)
    g = r.documento_indexado["gate_ocr"]

    assert g["metodo_por_pagina"] == {"1": "native", "2": "native"}
    for versao in g["extractor_version_por_pagina"].values():
        assert versao.startswith("pymupdf-")


def test_documento_indexado_desserializa_no_shared_sem_perda(monkeypatch):
    """Contrato entre repos (§9.3): o que o ai-agents serializa, o shared lê.

    É a fronteira que o `from_dict` do shared valida em produção, e o único
    teste que prova que os dois lados falam da mesma estrutura.
    """
    from garantis_shared.calculo_fichas.documento import DocumentoIndexado

    r = _indexar(pdf_nativo_puro(), OcrDuble(), monkeypatch)
    doc = DocumentoIndexado.from_dict(r.documento_indexado)

    assert doc.doc_id == "carf:raw/carf/1350272.pdf"
    assert len(doc.sentencas) > 0
    # round-trip: o que sai do shared volta a entrar igual
    assert DocumentoIndexado.from_dict(doc.to_dict()).to_dict() == doc.to_dict()


def test_ancora_resolvida_pelo_shared_valida_contra_o_proprio_documento(monkeypatch):
    """A âncora que o gate G1 vai usar. O lookup é do CÓDIGO, nunca do modelo."""
    from garantis_shared.calculo_fichas.documento import DocumentoIndexado

    r = _indexar(pdf_nativo_puro(), OcrDuble(), monkeypatch)
    doc = DocumentoIndexado.from_dict(r.documento_indexado)
    sid = doc.sentencas[0].sid

    ancora = doc.ancora_de(sid)
    assert ancora is not None
    ok, motivo = ancora.valida_contra(doc)
    assert ok and motivo == "", motivo


def test_valor_e_abreviacao_juridica_sobrevivem_como_UMA_sentenca(monkeypatch):
    """As duas armadilhas do §1.5, contra o texto que saiu do PDF de verdade.

    Não é reteste da segmentação (o shared já a testa): é a prova de que o
    caminho `PyMuPDF → canonicalizar → segmentar` preserva o que a segmentação
    garante quando o texto chega dela por outra porta.
    """
    r = _indexar(pdf_nativo_puro(1), OcrDuble(), monkeypatch)
    brutos = [s["texto_bruto"] for s in r.documento_indexado["sentencas"]]

    assert any("723.810.827,57" in t for t in brutos), "o valor virou pedaços"
    assert any("art. 142 do CTN" in t for t in brutos), "`art.` quebrou a sentença"


def test_bbox_preenchida_em_pagina_nativa_de_prosa_normal(monkeypatch):
    """Sem bbox, documento escaneado não tem reconferência humana nenhuma.

    A fixture aqui é prosa **sem repetição** de propósito: `pdf_nativo_puro`
    repete a mesma frase 20 vezes para exercitar o cursor, e nela a cobertura
    parcial é o comportamento correto (ver
    `test_MUTACAO_bbox_nunca_anda_para_TRAS_na_pagina`). Numa folha de acórdão
    de verdade, cada sentença é distinta e todas casam.
    """
    doc = pymupdf.open()
    _pagina_texto(
        doc,
        "ACORDAO CARF numero 1301-006.789. "
        + TEXTO_ACORDAO
        + " O relator destacou a divergencia entre as turmas ordinarias. "
        "A multa isolada foi cancelada por maioria de votos.",
    )
    r = _indexar(doc.tobytes(), OcrDuble(), monkeypatch)
    sentencas = r.documento_indexado["sentencas"]

    com_bbox = [s for s in sentencas if s["bbox"]]
    assert len(com_bbox) == len(sentencas), "toda sentença distinta tem coordenada"
    for s in com_bbox:
        x0, y0, x1, y1 = s["bbox"]
        assert x1 > x0 and y1 > y0, f"bbox degenerada em {s['sid']}"


# ═════════════════════════════════════════════════════════════════════════════
# 2. PDF MISTO — o gate acusa as páginas CERTAS
# ═════════════════════════════════════════════════════════════════════════════

def test_gate_acusa_exatamente_a_pagina_vetor_e_a_vazia(monkeypatch):
    """O coração da onda. Duas assimetrias, e as duas importam:

    - **falso-negativo** (deixar a folha 2 passar) ⇒ o dossiê perde a peça e a
      ficha sai `c4_sem_documentos` sem ninguém saber por quê;
    - **falso-positivo** (mandar 1 e 4 ao OCR) ⇒ 150× o custo num acórdão de 300
      folhas nativas, e a citação passa a ser contra texto OCR quando ela podia
      ser contra o PDF real.
    """
    doc = extracao.abrir_pdf(pdf_misto())
    textos = extracao.texto_nativo_por_pagina(doc)

    fora = gate.paginas_inalcancaveis(doc, textos)

    assert sorted(fora) == [2, 3], f"gate acusou {sorted(fora)}, esperado [2, 3]"
    assert fora[2] == gate.MOTIVO_VETOR
    assert fora[3] == gate.MOTIVO_VAZIA
    assert 1 not in fora and 4 not in fora, "página nativa NÃO vai ao OCR"


def test_misto_manda_ao_ocr_so_as_paginas_acusadas(monkeypatch):
    duble = OcrDuble()
    r = _indexar(pdf_misto(), duble, monkeypatch)

    assert r.success, r.error
    assert duble.chamadas == [[2, 3]], "só as inalcançáveis, e numa chamada só"
    assert r.paginas_ocr == [2, 3]


def test_misto_declara_metodo_por_pagina_e_extractor_discriminado(monkeypatch):
    """Um `metodo="misto"` sozinho não diz se a folha 12 é contra o PDF ou contra
    o OCR. O mapa por página é o que responde — e é o que a auditoria olha."""
    r = _indexar(pdf_misto(), OcrDuble(), monkeypatch)
    g = r.documento_indexado["gate_ocr"]

    assert r.metodo == "misto"
    assert g["metodo_por_pagina"] == {"1": "native", "2": "ocr", "3": "ocr", "4": "native"}
    assert g["extractor_version_por_pagina"]["1"].startswith("pymupdf-")
    assert g["extractor_version_por_pagina"]["2"].startswith("ocr-gemini-")
    # a do documento declara os DOIS: escolher um faria a outra metade mentir
    assert r.documento_indexado["extractor_version"].startswith("misto[")
    assert "pymupdf-" in r.documento_indexado["extractor_version"]
    assert "ocr-gemini-" in r.documento_indexado["extractor_version"]


def test_texto_do_ocr_SUBSTITUI_o_nativo_da_pagina_nunca_soma(monkeypatch):
    """Somar produziria a folha duas vezes — o carimbo e o texto completo — e a
    segmentação criaria dois `sid` para a mesma frase."""
    duble = OcrDuble({2: "Peca recuperada por OCR. Valor de R$ 55.000,00."})
    r = _indexar(pdf_misto(), duble, monkeypatch)

    pg2 = [s for s in r.documento_indexado["sentencas"] if s["pagina"] == 2]
    juntado = " ".join(s["texto_bruto"] for s in pg2)
    assert "OCR" in juntado
    assert "esaj.tjsp.jus.br" not in juntado, "o carimbo nativo sobreviveu ao OCR"


def test_pagina_de_ocr_sai_sem_bbox(monkeypatch):
    """OCR não devolve coordenada. Casar contra os spans do PyMuPDF apontaria
    para o CARIMBO — o lugar errado da imagem — e `documento.py` é explícito:
    *"um bbox inventado seria pior que ausente"*."""
    r = _indexar(pdf_misto(), OcrDuble(), monkeypatch)
    sentencas = r.documento_indexado["sentencas"]

    assert all(s["bbox"] is None for s in sentencas if s["pagina"] in (2, 3))
    assert any(s["bbox"] is not None for s in sentencas if s["pagina"] == 1)


def test_custo_do_ocr_sobe_ao_envelope(monkeypatch):
    """Custo invisível é o mecanismo que já escondeu US$ 97,61 em 39.309 calls."""
    r = _indexar(pdf_misto(), OcrDuble(custo=0.0042), monkeypatch)

    assert r.custo == pytest.approx(0.0042)
    assert r.cost_usd == pytest.approx(0.0042)
    assert r.model == "gemini-3.1-flash-lite"


def test_falha_do_ocr_nao_derruba_a_indexacao(monkeypatch):
    """O OCR é melhoria da leitura, não pré-condição dela: um PDF de 300 folhas
    nativas não pode deixar de ser indexado porque 2 folhas anexadas falharam."""
    async def _ocr_quebrado(provider, pdf_bytes, paginas, *, model=None):
        return {}, {"model": None, "cost_usd": 0.0, "erro": "Gemini 400"}

    monkeypatch.setattr(A, "ocr_paginas", _ocr_quebrado)
    monkeypatch.setattr(A, "_provider", lambda nome: object())
    r = asyncio.run(A.indexar(IndexarRequest(
        doc_id="d", pdf_base64=base64.b64encode(pdf_misto()).decode(),
    )))

    assert r.success, r.error
    assert r.metodo == "native", "sem OCR entregue, o que existe é nativo"
    assert r.paginas_ocr == []
    assert r.gate_ocr["n_inalcancaveis"] == 2, "a lacuna fica DECLARADA"


# ═════════════════════════════════════════════════════════════════════════════
# 3. DETERMINISMO — mesmo PDF ⇒ mesmo hash de saída
# ═════════════════════════════════════════════════════════════════════════════

def _hash_saida(documento: dict) -> str:
    """Hash canônico do `DocumentoIndexado`, com os voláteis FORA (§7.4).

    Fora do hash: o bloco `ocr` (custo, tokens, modelo resolvido) — é `_debug`
    por definição do desenho. Dentro: tudo que a âncora referencia.
    """
    limpo = {k: v for k, v in documento.items() if k != "gate_ocr"}
    limpo["gate_ocr"] = {
        k: v for k, v in (documento.get("gate_ocr") or {}).items() if k != "ocr"
    }
    return hashlib.sha256(
        json.dumps(limpo, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def test_mesmo_pdf_produz_hash_de_saida_identico(monkeypatch):
    """A garantia que o dono compra a cache frio no caminho SEM modelo.

    Nada entre o passo 1 e o 7 depende de tempo, de `hash()` builtin, de ordem
    de iteração de `set`, ou de qualquer coisa que mude entre dois processos.
    """
    pdf = pdf_nativo_puro(3)
    a = _indexar(pdf, OcrDuble(), monkeypatch)
    b = _indexar(pdf, OcrDuble(), monkeypatch)

    assert _hash_saida(a.documento_indexado) == _hash_saida(b.documento_indexado)


def test_determinismo_vale_tambem_no_caminho_misto(monkeypatch):
    """Com o OCR fixo (é o que o cache garante em produção), o misto também é
    determinístico — a variabilidade que resta é a do modelo, e é ela que o
    cache do §7 remove."""
    pdf = pdf_misto()
    a = _indexar(pdf, OcrDuble({2: "Texto fixo do OCR.", 3: "Outro texto fixo."}), monkeypatch)
    b = _indexar(pdf, OcrDuble({2: "Texto fixo do OCR.", 3: "Outro texto fixo."}), monkeypatch)

    assert _hash_saida(a.documento_indexado) == _hash_saida(b.documento_indexado)


def test_doc_hash_e_do_PDF_CRU_e_nao_do_texto(monkeypatch):
    """`doc_hash` responde "o blob no GCS mudou?" (§1.6). Hash do texto
    responderia outra pergunta e deixaria passar troca de PDF que produz o
    mesmo texto."""
    pdf = pdf_nativo_puro(1)
    r = _indexar(pdf, OcrDuble(), monkeypatch)

    assert r.documento_indexado["doc_hash"] == hashlib.sha256(pdf).hexdigest()


def test_hash_congelado_divergente_falha_TIPADO(monkeypatch):
    """§1.6: se o PDF mudou entre o `/start` e o S2b, o step falha. Ler
    silenciosamente outro documento é o modo de falha caro."""
    r = _indexar(
        pdf_nativo_puro(1), OcrDuble(), monkeypatch, doc_hash="0" * 64,
    )

    assert not r.success
    assert r.error == A.ERRO_HASH


# ═════════════════════════════════════════════════════════════════════════════
# 4. MUTAÇÃO — o que TEM que quebrar (§9.1)
# ═════════════════════════════════════════════════════════════════════════════

def test_MUTACAO_gate_que_ignora_o_sinal_de_pagina_deixa_o_vetor_passar():
    """Mutação: trocar o gate por página por `texto_lixo` sozinho.

    O carimbo do ESAJ é português impecável e `garbage_ratio` ≈ 0 — o Sinal 2
    sozinho o aprova, a peça fica presa na imagem, e ninguém percebe. É o furo
    medido no MS 1012150-95.2026.8.26.0224 (caso Steel, 2026-08-12).
    """
    from src.agents._utils.ocr_gate import texto_lixo

    doc = extracao.abrir_pdf(pdf_misto())
    textos = extracao.texto_nativo_por_pagina(doc)

    assert not texto_lixo(textos[2]), "premissa: o carimbo passa pelo rmgarbage"
    assert 2 in gate.paginas_inalcancaveis(doc, textos), "o gate real TEM que pegar"


def test_MUTACAO_teor_medido_por_len_cru_derrota_o_carimbo_multiplicado():
    """Mutação: medir o piso de TEOR por `len()` em vez de `texto_util_len`.

    O carimbo repete 1× por página: 6 × 340 = 2.044 ≥ 400, e o PDF nunca desceria
    ao Sinal 1. A régua correta é a do `garantis_shared.texto_util`.
    """
    from src.agents._utils.ocr_gate import TEOR_MIN_CHARS, texto_decide_sozinho

    seis = "".join(CARIMBO.format(n=i) + "\n\n" for i in range(1, 7))
    assert len(seis) > TEOR_MIN_CHARS * 4, "premissa: passa do piso CRU"
    assert not texto_decide_sozinho(seis), "o piso de TEOR tem que reprovar"


def test_MUTACAO_extractor_version_sem_o_metodo_nao_invalida_a_ancora():
    """Mutação: tirar o método da `extractor_version`.

    Reler por OCR uma folha antes lida nativamente muda o texto. Se a versão não
    codificasse o método, ela continuaria igual, a `Ancora` continuaria "válida"
    e apontaria para um texto que não existe mais — o modo silencioso que a
    âncora inteira existe para acabar.
    """
    nativa = extracao.extractor_version_de("native")
    ocr = extracao.extractor_version_de("ocr", modelo_ocr="gemini-3.1-flash-lite")

    assert nativa != ocr, "os dois métodos NÃO podem colidir na mesma versão"
    assert "ocr-" in ocr and "pymupdf-" in nativa


def test_MUTACAO_ancora_de_documento_reindexado_por_OCR_e_rejeitada(monkeypatch):
    """A prova de ponta a ponta da mutação anterior, pelo gate G1 do shared.

    Mesmo PDF, mesmo `sid`: a âncora do documento nativo tem que ser REJEITADA
    contra o documento reindexado por OCR — e rejeitada com motivo TIPADO, não
    por um fuzzy que "quase casa".
    """
    from garantis_shared.calculo_fichas.documento import (
        MOTIVO_ANCORA_APODRECIDA,
        DocumentoIndexado,
    )

    pdf = pdf_nativo_puro(1)
    nativo = DocumentoIndexado.from_dict(
        _indexar(pdf, OcrDuble(), monkeypatch).documento_indexado
    )
    ancora = nativo.ancora_de(nativo.sentencas[0].sid)

    # o MESMO documento, agora com a folha 1 vinda do OCR
    reindexado, erro = A.montar_documento_indexado(
        doc_id=nativo.doc_id,
        doc_hash=nativo.doc_hash,
        n_paginas=1,
        textos_nativos={1: ""},
        textos_ocr={1: TEXTO_ACORDAO},
        spans={},
        gate_ocr={"n_paginas": 1, "n_inalcancaveis": 1},
        modelo_ocr="gemini-3.1-flash-lite",
    )
    assert erro is None

    ok, motivo = ancora.valida_contra(reindexado)
    assert not ok
    assert motivo == MOTIVO_ANCORA_APODRECIDA


def test_MUTACAO_bbox_nunca_anda_para_TRAS_na_pagina(monkeypatch):
    """Mutação real, pega por este teste durante a construção: reiniciar a busca
    do topo da página quando o cursor não acha mais a palavra-âncora.

    A tentação é "melhor um bbox fora de ordem que nenhum", e ela está errada em
    texto que se REPETE — cabeçalho, rodapé, carimbo, a fórmula do relator, e é
    por isso que a fixture repete a mesma frase 20 vezes. Com o reinício, uma
    ocorrência do fim da folha casava na primeira e a bbox apontava para o TOPO
    da página enquanto a sentença estava no rodapé.

    A assimetria que decide (`documento.py::_bbox_valida`): bbox ausente degrada
    a reconferência — o humano ainda tem `sid` + `pagina` + `texto_bruto`; bbox
    ERRADA manda a pessoa olhar para o lugar errado, ela não acha o trecho e
    conclui que a citação é falsa, reprovando a evidência CERTA.
    """
    r = _indexar(pdf_nativo_puro(1), OcrDuble(), monkeypatch)
    pg1 = [s for s in r.documento_indexado["sentencas"] if s["pagina"] == 1 and s["bbox"]]

    tops = [s["bbox"][1] for s in pg1]
    assert tops == sorted(tops), "as bboxes têm que descer a página, nunca voltar"
    assert tops[-1] > tops[0], "premissa: a fixture ocupa mais de uma linha"
    assert len(set(tops)) > 3, (
        "premissa: as ocorrências repetidas se espalham pela folha — é esse o "
        "caso em que o reinício produzia a caixa errada"
    )


def test_MUTACAO_cursor_que_pula_o_span_perde_as_sentencas_da_MESMA_linha():
    """Mutação real, também pega na construção: avançar o cursor para
    `ultimo_span + 1` depois de casar.

    Um span do PyMuPDF é uma LINHA, e uma linha de acórdão carrega 2-3 sentenças
    ("…R$ 723.810.827,57. Nos termos do art. 142…"). Pulando a linha, a sentença
    seguinte — que começa nela — procura a partir da linha de baixo e sai com
    `bbox=None` mesmo sendo perfeitamente localizável. Medido: **3 de 6**
    sentenças de uma folha de prosa normal perdiam a coordenada.

    O teste é direto sobre `atribuir_bboxes` com DUAS sentenças no MESMO span —
    é o mínimo que reproduz o defeito, sem depender do layout do PDF.
    """
    from garantis_shared.calculo_fichas.documento import Sentenca

    linha = extracao.SpanPagina(
        "Primeira afirmacao relevante. Segunda afirmacao relevante.", 0, (10.0, 20.0, 400.0, 32.0)
    )
    sentencas = (
        Sentenca(sid="fl1-s1", texto="primeira afirmacao relevante.",
                 texto_bruto="Primeira afirmacao relevante.", pagina=1,
                 par_id="fl1-p1", offset=0, bbox=None),
        Sentenca(sid="fl1-s2", texto="segunda afirmacao relevante.",
                 texto_bruto="Segunda afirmacao relevante.", pagina=1,
                 par_id="fl1-p1", offset=30, bbox=None),
    )

    a, b = extracao.atribuir_bboxes(sentencas, {1: [linha]})

    assert a.bbox is not None, "a primeira sempre casou"
    assert b.bbox is not None, (
        "a segunda sentença da MESMA linha tem que casar — se ela sai None, o "
        "cursor voltou a pular o span"
    )
    assert a.bbox == b.bbox, "mesma linha ⇒ mesma caixa; é a verdade do layout"


def test_sentenca_nao_localizavel_sai_com_bbox_None_e_nao_com_caixa_errada(monkeypatch):
    """O que acontece com quem NÃO casa — e no caso real isso acontece.

    O caso concreto: página cujo texto veio do OCR (sem coordenada nenhuma) e
    cujos spans nativos contêm outra coisa. Aqui é simulado direto no
    `atribuir_bboxes`, que é onde a decisão mora.

    `None` é valor legítimo no contrato do shared e é o que o `pedir_pagina` e a
    fila de exceção sabem tratar. Uma caixa "aproximada" seria indistinguível de
    uma correta para quem lê a ficha.
    """
    from garantis_shared.calculo_fichas.documento import Sentenca

    sentenca = Sentenca(
        sid="fl1-s1", texto="valor irrecuperavel", texto_bruto="Valor irrecuperavel",
        pagina=1, par_id="fl1-p1", offset=0, bbox=None,
    )
    spans = {1: [extracao.SpanPagina("texto completamente diferente", 0, (1.0, 2.0, 3.0, 4.0))]}

    (saida,) = extracao.atribuir_bboxes((sentenca,), spans)

    assert saida.bbox is None, "não casou ⇒ None, NUNCA a caixa do span vizinho"
    # o que sobra continua levando o humano à folha certa
    assert saida.sid == "fl1-s1" and saida.pagina == 1 and saida.texto_bruto


# ═════════════════════════════════════════════════════════════════════════════
# 5. O PARSER DO OCR e o PROMPT
# ═════════════════════════════════════════════════════════════════════════════

def test_parser_do_ocr_separa_as_paginas_pelos_marcadores():
    saida = "preambulo do modelo\n<<<PG:2>>>\nTexto da folha 2.\n<<<PG:5>>>\nTexto da folha 5."

    assert O.parse_paginas_ocr(saida, [2, 5]) == {
        2: "Texto da folha 2.", 5: "Texto da folha 5.",
    }


def test_parser_do_ocr_descarta_pagina_que_nao_foi_pedida():
    """Aceitá-la escreveria texto de OCR sobre uma página NATIVA — trocaria uma
    citação forte (contra o PDF) por uma fraca (contra o OCR), sem sinal."""
    saida = "<<<PG:2>>>\nok\n<<<PG:9>>>\ninventada"

    assert O.parse_paginas_ocr(saida, [2]) == {2: "ok"}


def test_parser_do_ocr_nao_transforma_pagina_ausente_em_vazia():
    """Chave ausente = "o OCR não devolveu esta folha". `""` afirmaria que a
    folha está em branco — uma afirmação sobre o documento sem base."""
    assert O.parse_paginas_ocr("<<<PG:2>>>\nok", [2, 3]) == {2: "ok"}


def test_parser_do_ocr_aceita_resposta_sem_marcador_quando_ha_1_pagina_so():
    """Modelo ignorar o formato é o modo de falha comum; com uma página só não
    há ambiguidade sobre onde o texto vai."""
    assert O.parse_paginas_ocr("Texto puro sem marcador.", [7]) == {7: "Texto puro sem marcador."}


def test_parser_do_ocr_descarta_resposta_sem_marcador_com_N_paginas():
    """Com N páginas, atribuir tudo à primeira seria inventar a localização."""
    assert O.parse_paginas_ocr("Texto puro sem marcador.", [7, 8]) == {}


def test_prompt_de_ocr_proibe_corrigir_e_lista_as_folhas_na_ordem():
    """A instrução mais importante: o modelo "consertar" `723.810.827,57`
    transforma a citação em algo que não está no documento, e o gate G2 reprova
    a evidência CERTA."""
    p = O.montar_prompt_ocr([5, 2])

    assert "<<<PG:2>>>" in p and "<<<PG:5>>>" in p
    assert p.index("<<<PG:2>>>") < p.index("<<<PG:5>>>"), "ordem crescente"
    assert "LITERALMENTE" in p
    assert "Não corrija" in p and "Não invente" not in p.replace("Nunca invente", "")


def test_ocr_usa_o_papel_do_ROLES_e_nao_um_modelo_hard_coded(monkeypatch):
    """§8.4: *"modelos pelo ROLES, nunca hard-code"*. O `pdf_text.py` fixa
    `gemini-2.5-flash-lite`, família que APOSENTA em 16/10/2026 — este é o
    débito que a onda 2 não herda."""
    from garantis_shared.llm_models import MODELS, model_for

    monkeypatch.delenv("DOC_INDEXER_OCR_MODEL", raising=False)

    assert O.modelo_ocr() == model_for(O.PAPEL_OCR)
    assert O.modelo_ocr() in MODELS, "modelo fora do catálogo ⇒ preço 0/0, gasto invisível"
    assert "2.5" not in O.modelo_ocr()


def test_env_sobrepoe_o_papel_do_ROLES(monkeypatch):
    monkeypatch.setenv("DOC_INDEXER_OCR_MODEL", "gemini-3.5-flash")
    assert O.modelo_ocr() == "gemini-3.5-flash"


def test_recorte_de_paginas_produz_pdf_so_com_as_folhas_pedidas():
    """Mandar o PDF inteiro e pedir "transcreva as folhas 2 e 3" custa o
    documento inteiro em input e depende de o modelo contar páginas certo — que
    é onde ele erra. O recorte devolve a contagem ao código."""
    recorte = O.recortar_paginas(pdf_misto(), [2, 4])

    assert recorte is not None
    assert len(pymupdf.open(stream=recorte, filetype="pdf")) == 2


def test_ocr_sem_paginas_nao_chama_modelo_nenhum():
    textos, tele = asyncio.run(O.ocr_paginas(object(), b"%PDF-1.4", []))

    assert textos == {} and tele["cost_usd"] == 0.0 and tele["model"] is None


# ═════════════════════════════════════════════════════════════════════════════
# 6. FLAG, ENVELOPE e ENTRADAS RUINS
# ═════════════════════════════════════════════════════════════════════════════

def test_flag_off_devolve_sucesso_falso_sem_tocar_em_nada(monkeypatch):
    """Ship inerte + flip explícito (`llm_seed.py`). Com a flag OFF a rota não
    baixa PDF, não abre PyMuPDF e não chama modelo."""
    monkeypatch.setenv(A.FLAG_DOC_INDEXER, "false")
    chamou = []
    monkeypatch.setattr(A, "_obter_bytes", lambda req: chamou.append(1))

    r = asyncio.run(A.indexar(IndexarRequest(doc_id="d", pdf_base64="Zm9v")))

    assert not r.success and r.error == A.ERRO_FLAG_OFF
    assert chamou == []


def test_flag_default_e_OFF(monkeypatch):
    """O default do desenho (§8.5) é `false`. Se isto inverter, o PR deixa de ser
    byte-idêntico quando mergeado."""
    monkeypatch.delenv(A.FLAG_DOC_INDEXER, raising=False)

    r = asyncio.run(A.indexar(IndexarRequest(doc_id="d", pdf_base64="Zm9v")))
    assert r.error == A.ERRO_FLAG_OFF


def test_pdf_ilegivel_devolve_erro_TIPADO_e_nao_documento_vazio(monkeypatch):
    """6 de 20 "PDFs" de uma amostra real são HTML/RTF sob nome `.pdf`. Um
    documento indexado vazio pareceria um PDF em branco legítimo."""
    r = asyncio.run(A.indexar(IndexarRequest(
        doc_id="d", pdf_base64=base64.b64encode(b"<p>nao sou um pdf</p>").decode(),
    )))

    assert not r.success
    assert r.error == A.ERRO_PDF_ILEGIVEL
    assert r.documento_indexado is None


def test_pdf_sem_texto_algum_devolve_erro_TIPADO(monkeypatch):
    """PDF de uma folha em branco e sem OCR entregue: não há o que indexar, e
    dizer `success=true` com zero sentenças mentiria para o step S2b."""
    doc = pymupdf.open()
    doc.new_page()
    monkeypatch.setattr(A, "_provider", lambda nome: None)

    r = asyncio.run(A.indexar(IndexarRequest(
        doc_id="d", pdf_base64=base64.b64encode(doc.tobytes()).decode(),
    )))

    assert not r.success and r.error == A.ERRO_VAZIO


def test_sem_gcs_path_nem_base64_falha_TIPADO():
    r = asyncio.run(A.indexar(IndexarRequest(doc_id="d")))
    assert not r.success and r.error == A.ERRO_SEM_FONTE


def test_base64_invalido_falha_TIPADO():
    r = asyncio.run(A.indexar(IndexarRequest(doc_id="d", pdf_base64="!!!nao-e-base64!!!")))
    assert not r.success and r.error == A.ERRO_BASE64


def test_rota_registrada_no_app_com_o_prefixo_do_desenho():
    """Pelo OpenAPI e não por `app.routes`: o schema é o contrato que o shared
    consome, e `app.routes` traz objetos internos do FastAPI que mudam de forma
    entre versões (`_IncludedRouter` sem `.path` nesta)."""
    from src.api.main import app

    assert "/doc-indexer/indexar" in app.openapi()["paths"]


def test_envelope_da_rota_tem_os_campos_que_o_desenho_pede(monkeypatch):
    """§P/onda 2: `{success, documento_indexado, custo, paginas_ocr}`."""
    r = _indexar(pdf_nativo_puro(1), OcrDuble(), monkeypatch)
    corpo = r.model_dump()

    for campo in ("success", "documento_indexado", "custo", "paginas_ocr"):
        assert campo in corpo, f"o envelope perdeu `{campo}`"
    # e o envelope da casa, que todo endpoint do repo carrega
    for campo in ("model", "cost_usd", "error"):
        assert campo in corpo

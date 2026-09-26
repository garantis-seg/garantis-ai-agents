"""O C5 le o candidato SCAN (fatia 2 da cabeca dos autos, card 869equgwd, OK Elton 15/09).

O Vision so TRANSCREVE as N primeiras paginas do scan; a transcricao vira o `head` e o
julgamento e a MESMA chamada de texto medida. ⛔ Nenhum PDF entra na chamada que julga
(gold scan 15/09: misturado contaminou o texto; so-scans afirmou inicial de outro processo).
"""
from __future__ import annotations

import io
from types import SimpleNamespace

import pytest
from pypdf import PdfReader, PdfWriter

from src.agents._utils import ocr_gate
from src.agents.peticao_confirmador import agent as agent_mod
from tests import test_peticao_confirmador_rota as _rota
from tests.test_peticao_confirmador_rota import (HEAD_1, HEAD_2, ROTA, _mock_provider,
                                                 _req, _veredito)

#: a fixture `client` da rota, exposta aqui por ATRIBUICAO: importada pelo nome, o
#: parametro `client` de cada teste vira redefinicao do import (F811).
client = _rota.client


def _pdf(paginas: int) -> bytes:
    w = PdfWriter()
    for _ in range(paginas):
        w.add_blank_page(width=100, height=100)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def _vision_fake(monkeypatch, texto="EXCELENTISSIMO SENHOR JUIZ transcrito do scan",
                 falha=False):
    """Transcricao duble. PDFs por URL: `gs://b/<paginas>` ou `gs://b/sumido`."""
    chamadas: list[dict] = []

    async def _fetch(urls):
        return [] if urls[0].endswith("sumido") else [_pdf(int(urls[0].rsplit("/", 1)[1]))]

    async def _call(provider, **kw):
        chamadas.append(kw)
        if falha:
            raise RuntimeError("400 The document has no pages")
        return SimpleNamespace(text=f"{texto} #{len(chamadas)}", model=kw["model"],
                               input_tokens=900, output_tokens=300, cached_tokens=0,
                               metadata={"cost_usd": 0.0009, "model_variant": "vision"})

    monkeypatch.setattr(agent_mod, "fetch_pdfs_from_gcs", _fetch)
    monkeypatch.setattr(agent_mod, "call_vision_l1", _call)
    return chamadas


def _scan(n, url):
    return {"n": n, "doc_key": f"esc-{n}", "titulo": "Auto", "head": "", "gcs_url": url}


def _pool_misto(**over):
    req = _req(**over)
    t1, t2, _ = req["candidatos"]
    req["candidatos"] = [t1, _scan(2, "gs://b/40"), t2, _scan(4, "gs://b/3")]
    return req


def test_pool_sem_scan_nao_chama_Vision(client, monkeypatch):
    """⛔ MUTANTE: transcrever todo candidato com `gcs_url`. `head` presente = texto."""
    vis = _vision_fake(monkeypatch)
    fake = _mock_provider(monkeypatch, _veredito(1))
    req = _req()
    req["candidatos"][0]["gcs_url"] = "gs://b/3"
    body = client.post(ROTA, json=req).json()
    assert vis == [] and fake.n_chamadas == 1
    assert body["usage"]["model_variant"] != "vision"


def test_scan_vira_TEXTO_e_o_julgamento_e_UMA_chamada_sem_PDF(client, monkeypatch):
    """⛔ MUTANTE: mandar o PDF pra chamada que julga (o desenho refutado no gold de 15/09)."""
    vis = _vision_fake(monkeypatch)
    fake = _mock_provider(monkeypatch, _veredito(2))
    body = client.post(ROTA, json=_pool_misto()).json()

    assert len(vis) == 2, "1 transcricao POR scan"
    assert all(kw["prompt"] == agent_mod._TRANSCREVA for kw in vis)
    assert all(kw["seed"] == agent_mod._SEED_TRANSCRICAO and kw["temperature"] == 0.0
               for kw in vis)
    assert [len(PdfReader(io.BytesIO(kw["pdf_bytes_list"][0])).pages) for kw in vis] == [2, 2]
    assert "response_schema" not in vis[0] or vis[0].get("response_schema") is None, \
        "transcricao e extracao, nao veredito"

    assert fake.n_chamadas == 1, "o julgamento continua UMA chamada comparativa"
    julg = fake.chamadas[0]
    assert "pdf_bytes_list" not in julg
    prompt = julg["prompt"]
    assert "Escolha entre os candidatos [1] a [4]" in prompt, "os 4 juntos, na ordem"
    assert prompt.index(HEAD_1) < prompt.index("transcrito do scan #1") < prompt.index(HEAD_2) \
        < prompt.index("transcrito do scan #2"), "a transcricao ocupa a POSICAO do scan"
    assert "gs://" not in prompt
    assert body["card"]["escolhido"] == 2, "card cru, numeracao do pool"
    assert body["usage"]["cost_usd"] == pytest.approx(0.0001 + 2 * 0.0009)
    assert body["usage"]["model_variant"] == "vision"
    assert body["nao_transcritos"] == [], "os 2 scans foram lidos"


def test_a_transcricao_e_cortada_na_janela_DECLARADA(client, monkeypatch):
    """A janela anti-copia vale pro scan tambem: a inicial alheia abre ~char 3.914."""
    _vision_fake(monkeypatch, texto="A" * 40 + "SEGREDO_ALEM_DA_JANELA")
    fake = _mock_provider(monkeypatch, _veredito(0))
    req = _req(head_chars=50)
    req["candidatos"] = [_scan(1, "gs://b/2")]
    client.post(ROTA, json=req)
    assert "SEGREDO_ALEM_DA_JANELA" not in fake.chamadas[0]["prompt"]


@pytest.mark.parametrize("url,falha", [("gs://b/sumido", False), ("gs://b/2", True)])
def test_scan_sem_transcricao_segue_no_pool_como_marca(client, monkeypatch, url, falha):
    """PDF indisponivel ou Vision quebrado NAO derruba a pergunta: o candidato vai sem
    conteudo, e o C5 julga os demais. ⛔ MUTANTE: esconder do caller que o scan foi julgado sem
    conteudo — o `garantis_shared` o daria por JULGADO e o terminal da peticao soltaria um
    afirmativo que ninguem leu."""
    _vision_fake(monkeypatch, falha=falha)
    fake = _mock_provider(monkeypatch, _veredito(1))
    req = _req()
    req["candidatos"] = [req["candidatos"][0], _scan(2, url)]
    resp = client.post(ROTA, json=req)
    assert resp.status_code == 200 and fake.n_chamadas == 1
    assert agent_mod._MARCA_SEM_PDF in fake.chamadas[0]["prompt"]
    assert resp.json()["nao_transcritos"] == ["esc-2"], "so o scan sem leitura, nao o texto"


def test_inicio_do_pdf_corta_so_o_COMECO():
    assert len(PdfReader(io.BytesIO(ocr_gate.inicio_do_pdf(_pdf(41), 2))).pages) == 2
    curto = _pdf(1)
    assert ocr_gate.inicio_do_pdf(curto, 2) is curto
    assert ocr_gate.inicio_do_pdf(b"<p>html</p>", 2) is None

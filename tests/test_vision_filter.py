"""Vision-L1 unreadable-PDF filter + error guard + 3.1-lite pricing.

Guards the 2026-06-28 vision-L1 image-doc test findings: ~46% of "addressable"
jusbrasil PDFs are a byte-identical access-restricted stub, some are 0-page
corrupt blobs that make Gemini Vision 400. Both must be dropped before the call
(→ cheap text fallback), and a Vision error must never crash the cascade.
"""
import hashlib

import fitz  # PyMuPDF (dep)

import src.agents._utils.vision as V


def _pdf(text: str = "conteudo", pages: int = 1) -> bytes:
    doc = fitz.open()
    for _ in range(pages):
        p = doc.new_page()
        if text:
            p.insert_text((72, 72), text)
    return doc.tobytes()


def test_pricing_31_flash_lite_present():
    from src.providers.gemini import GEMINI_PRICING

    assert GEMINI_PRICING["gemini-3.1-flash-lite"] == {
        "input_per_1m": 0.25,
        "output_per_1m": 1.50,
    }


def test_normal_pdf_is_readable():
    assert V._pdf_is_unreadable(_pdf("texto real", pages=1)) is False


def test_known_stub_hash_is_unreadable(monkeypatch):
    blob = _pdf("acesso restrito", 1)
    h = hashlib.sha256(blob).hexdigest()
    monkeypatch.setattr(
        V, "_KNOWN_UNREADABLE_PDF_SHA256", V._KNOWN_UNREADABLE_PDF_SHA256 | {h}
    )
    assert V._pdf_is_unreadable(blob) is True


async def test_fetch_drops_stub(monkeypatch):
    good, stub = _pdf("bom", 1), _pdf("acesso restrito", 1)
    monkeypatch.setattr(
        V,
        "_KNOWN_UNREADABLE_PDF_SHA256",
        V._KNOWN_UNREADABLE_PDF_SHA256 | {hashlib.sha256(stub).hexdigest()},
    )
    by_url = {"gs://b/good.pdf": good, "gs://b/stub.pdf": stub}

    async def fake_bytes(_client, url):
        return by_url[url]

    monkeypatch.setattr(V, "_get_storage_client", lambda: object())
    monkeypatch.setattr(V, "_fetch_pdf_bytes", fake_bytes)
    out = await V.fetch_pdfs_from_gcs(["gs://b/good.pdf", "gs://b/stub.pdf"])
    assert out == [good]


async def test_vision_error_falls_back_to_text(monkeypatch):
    sentinel = object()

    class FakeProvider:
        async def agenerate(self, **_kw):
            return sentinel

    async def _bytes(_urls):
        return [b"%PDF-1.4 fake"]

    async def _boom(*_a, **_k):
        raise RuntimeError("400 INVALID_ARGUMENT document has no pages")

    monkeypatch.setenv("VISION_L1_ENABLED", "true")
    monkeypatch.setattr(V, "fetch_pdfs_from_gcs", _bytes)
    monkeypatch.setattr(V, "call_vision_l1", _boom)

    res = await V.call_l1_with_vision_fallback(
        FakeProvider(), model="m", prompt="p",
        gcs_urls=["gs://b/x.pdf"], response_schema=None,
    )
    assert res is sentinel  # guard fell through to text-only


if __name__ == "__main__":
    import sys

    sys.exit(__import__("pytest").main([__file__, "-q"]))

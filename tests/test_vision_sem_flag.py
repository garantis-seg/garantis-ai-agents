"""O ramo Vision do L1 roda sem flag de env: basta o caller mandar o gcs_url.

O `VISION_L1_ENABLED` valia true em prod e na demo, entao o ramo OFF (gcs_url ignorado,
so texto) nao rodava. A flag saiu: nem o valor false desliga o Vision.
"""
import src.agents._utils.vision as V


async def test_a_env_false_nao_desliga_o_vision(monkeypatch):
    visto: list = []

    async def _bytes(_urls):
        return [b"%PDF-1.4 fake"]

    async def _vision(provider, **kw):
        visto.append(kw)
        return "resposta-vision"

    class _SoTexto:
        async def agenerate(self, **_kw):
            return "resposta-texto"

    monkeypatch.setenv("VISION_L1_ENABLED", "false")
    monkeypatch.setattr(V, "fetch_pdfs_from_gcs", _bytes)
    monkeypatch.setattr(V, "call_vision_l1", _vision)

    res = await V.call_l1_with_vision_fallback(
        _SoTexto(), model="m", prompt="p", gcs_urls=["gs://b/x.pdf"], response_schema=None,
    )
    assert res == "resposta-vision" and len(visto) == 1

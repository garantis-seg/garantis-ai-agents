"""O `tipo_judicial` do L2 vem do cliente (o shared), sempre. Sem ele a rota recusa, em
vez de afirmar `civel` por default."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

import src.api.routes.processo_synthesis as route_mod


def test_sem_tipo_judicial_a_rota_recusa(monkeypatch):
    chamou = []

    async def _fake_classify(*a, **k):
        chamou.append(1)
        return {"card": {}, "raw_response": {}, "llm_raw_prompt": {}, "usage": {}}

    monkeypatch.setattr(route_mod, "classify_processo_synthesis", _fake_classify)
    app = FastAPI()
    app.include_router(route_mod.router)
    r = TestClient(app).post("/processo-synthesis/classify",
                             json={"processo_numero": "1", "mov_factsheets": []})
    assert r.status_code == 422, r.text
    assert "tipo_judicial" in r.text
    assert not chamou

"""O corpo do pedido comprimido com gzip chega às rotas como JSON cru."""
import gzip
import json

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from src.api.middleware import CorpoGzipMiddleware


def _app(teto: int = 1024 * 1024) -> TestClient:
    app = FastAPI()
    app.add_middleware(CorpoGzipMiddleware, teto=teto)

    @app.post("/eco")
    async def eco(req: Request, corpo: dict):
        return {"n": len(corpo.get("texto", "")), "encoding": req.headers.get("content-encoding"),
                "tamanho": req.headers.get("content-length")}

    return TestClient(app)


def _gz(obj) -> bytes:
    return gzip.compress(json.dumps(obj).encode())


def test_o_corpo_comprimido_chega_inteiro_e_sem_o_cabecalho():
    texto = "acórdão " * 50_000
    r = _app().post("/eco", content=_gz({"texto": texto}),
                    headers={"Content-Encoding": "gzip", "Content-Type": "application/json"})
    assert r.status_code == 200
    cru = len(json.dumps({"texto": texto}).encode())
    assert r.json() == {"n": len(texto), "encoding": None, "tamanho": str(cru)}


def test_o_pedido_sem_gzip_passa_sem_toque():
    r = _app().post("/eco", json={"texto": "abc"})
    assert r.status_code == 200 and r.json()["n"] == 3


def test_o_corpo_que_nao_e_gzip_da_400():
    r = _app().post("/eco", content=b"{\"texto\": \"abc\"}",
                    headers={"Content-Encoding": "gzip", "Content-Type": "application/json"})
    assert r.status_code == 400 and "gzip" in r.json()["detail"]


def test_o_corpo_gzip_cortado_da_400():
    r = _app().post("/eco", content=_gz({"texto": "x" * 5000})[:-12],
                    headers={"Content-Encoding": "gzip", "Content-Type": "application/json"})
    assert r.status_code == 400


def test_o_corpo_acima_do_teto_da_413():
    r = _app(teto=1000).post("/eco", content=_gz({"texto": "x" * 5000}),
                             headers={"Content-Encoding": "gzip", "Content-Type": "application/json"})
    assert r.status_code == 413

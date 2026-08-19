"""O endpoint `/celula-base/classify` foi REMOVIDO em 2026-08-19 (decisao Elton).

Par do garantis-shared#392, que removeu o piso celula-base do L3. O unico caller
era `classify_celula_base` do shared, gateado por `CELULA_BASE_CLASSIFIER_ENABLED`
-- flag que nasceu OFF em 2026-07-11 e nunca ligou, entao o endpoint teve ZERO
chamadas a vida inteira.

⛔ A guarda le as ROTAS MONTADAS (payload executavel), nunca o texto de `main.py`
-- que contem o nome na lapide.
"""
from __future__ import annotations

from src.api.main import app


def _paths() -> set[str]:
    return {getattr(r, "path", "") for r in app.routes}


def test_a_rota_celula_base_nao_esta_montada():
    assert not [p for p in _paths() if "celula-base" in p], \
        "/celula-base voltou a ser montada"


def test_os_VIZINHOS_continuam_montados():
    """Contra-exemplo: sem isto a assercao de ausencia passaria verde num `app`
    vazio ou quebrado. O `merito_reducao_v2` e o vizinho direto (mesmo B1)."""
    paths = _paths()
    for esperado in ("/merito-reducao-v2", "/merito-synthesis", "/mov-factsheet"):
        assert any(p.startswith(esperado) for p in paths), f"{esperado} sumiu junto"


def test_o_pacote_do_agent_nao_existe_mais():
    import importlib
    for mod in ("src.agents.celula_base_classifier", "src.api.routes.celula_base_classifier"):
        try:
            importlib.import_module(mod)
        except ModuleNotFoundError:
            continue
        raise AssertionError(f"{mod} voltou a existir")

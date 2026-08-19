"""O endpoint `/celula-base/classify` foi REMOVIDO em 2026-08-19 (decisao Elton).

Par do garantis-shared#392, que removeu o piso celula-base do L3. O unico caller
era `classify_celula_base` do shared, gateado por `CELULA_BASE_CLASSIFIER_ENABLED`
-- flag que nasceu OFF em 2026-07-11 e nunca ligou, entao o endpoint teve ZERO
chamadas a vida inteira.

🚨 **A 1a versao deste arquivo QUEBROU O DEPLOY, e pelo motivo que o vizinho
`test_edital_summarizer_removido.py` ja documentava** (2026-08-11): o
CONTRA-EXEMPLO nao pode olhar ROTA. Ele exigia `/merito-reducao-v2`,
`/merito-synthesis` e `/mov-factsheet` montados; passou local (669 passed) e
falhou no container do cloudbuild com *"/merito-reducao-v2 sumiu junto"*, com os
3 prefixos hardcoded e corretos nos routers. O inventario de `app.routes` **nao e
o mesmo nas duas maquinas**, entao um contra-exemplo que depende de como o `app` e
construido testa o AMBIENTE junto com o codigo. O risco real -- *alguem corta os
agentes do ENGINE por proximidade, porque moram no mesmo `main.py`* -- se testa por
IMPORT, que e o que este arquivo faz agora.

⛔ E a ausencia tambem nao se prova por `importlib`: `src/agents/celula_base_
classifier/__pycache__/` sobrevive a um `git rm` na arvore de quem ja rodou os
testes, e o diretorio orfao vira NAMESPACE PACKAGE -- importavel, sem fonte. A
prova de ausencia e o ARQUIVO-FONTE.
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"

_FONTES_QUE_SAIRAM = [
    "agents/celula_base_classifier/agent.py",
    "agents/celula_base_classifier/__init__.py",
    "api/routes/celula_base_classifier.py",
]

# Os 3 agentes do ENGINE moram no MESMO `src/agents/` e no mesmo `include_router`
# do que saiu. Se um teardown futuro cortar por proximidade, e aqui que fica
# vermelho -- `ModuleNotFoundError` = alguem levou o engine junto.
_AGENTES_DO_ENGINE_QUE_FICAM = [
    "src.agents.merito_reducao_v2",
    "src.agents.merito_synthesis",
    "src.agents.mov_factsheet",
]


@pytest.mark.parametrize("rel", _FONTES_QUE_SAIRAM)
def test_a_fonte_do_celula_base_nao_existe_mais(rel):
    assert not (_SRC / rel).exists(), f"src/{rel} voltou"


def test_o_router_nao_e_mais_montado_em_main():
    """`main.py` monta por `include_router(<mod>.router)` -- sem o modulo, um
    revert parcial (so o import) quebraria o BOOT, nao uma rota. Aqui se cobra o
    par: nem import, nem include."""
    main = (_SRC / "api" / "main.py").read_text(encoding="utf-8")
    linhas_vivas = [
        ln for ln in main.splitlines()
        if "celula_base_classifier" in ln and not ln.lstrip().startswith("#")
    ]
    assert linhas_vivas == [], f"main.py voltou a referenciar o router: {linhas_vivas}"


@pytest.mark.parametrize("modulo", _AGENTES_DO_ENGINE_QUE_FICAM)
def test_CONTRA_EXEMPLO_os_agentes_do_engine_continuam_existindo(modulo):
    assert importlib.import_module(modulo) is not None

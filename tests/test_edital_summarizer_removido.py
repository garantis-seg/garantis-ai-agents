"""Card 869egwv81 — o agente `edital_summarizer` saiu com o produto Licitacao (2026-08-11).

Ele era o 4o repo do teardown, e o unico que ninguem tinha olhado: o card nomeava 2
repos (licitacao-pipeline e execucao-fiscal) e a UI era o 3o. O agente aqui so ficou
visivel quando os DOIS callers dele morreram no mesmo dia — `frontend-api
routers/licitacao_summary.py` (ef#1340) e `whatsapp-bot services/edital_analyzer.py`
(bot#4).

⚠️ A leitura e do payload EXECUTAVEL (`app.routes`), nunca do texto de `main.py`:
o proprio arquivo cita "summarization" na lista de imports vizinha, entao um
`assert "summarization" not in texto` seria fragil pelo motivo errado.

⚠️⚠️ O CONTRA-EXEMPLO NAO OLHA ROTA, E ISSO E DELIBERADO — a 1a versao deste arquivo
olhava, e QUEBROU O DEPLOY. Ela exigia `/mov-factsheet`, `/processo-synthesis` e
`/merito-synthesis` montados; passou local (270 passed) e falhou no container do
cloudbuild com *"as rotas de /mov-factsheet sumiram"*, com os 3 prefixos hardcoded e
corretos nos 3 routers. Ou seja: o inventario de `app.routes` NAO e o mesmo nas duas
maquinas, e um contra-exemplo que depende de como o `app` e construido testa o
ambiente junto com o codigo. O risco que ele existe pra cobrir — *alguem corta os
agentes do ENGINE por proximidade, porque moram no mesmo `main.py`* — se testa melhor
no IMPORT, que nao depende de app, middleware, env nem da ordem dos outros testes.

⚠️ E a assercao de AUSENCIA nao passa vacuosamente num app quebrado: se
`src.api.main` nao importar, a fixture LEVANTA (o teste da error, nao green).
"""

import importlib

import pytest


@pytest.fixture(scope="module")
def rotas_montadas():
    from src.api.main import app

    return {getattr(r, "path", "") for r in app.routes}


def test_nenhuma_rota_de_summarization_montada(rotas_montadas):
    vivas = sorted(p for p in rotas_montadas if p.startswith("/summarization"))
    assert vivas == [], f"as rotas do edital_summarizer voltaram a ser montadas: {vivas}"


def test_o_pacote_do_agente_nao_existe_mais():
    """O import e a prova real: a rota podia sair e o agente ficar, virando 990 linhas
    de codigo inalcancavel — que era exatamente o estado que este PR encontrou."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("src.agents.edital_summarizer")


@pytest.mark.parametrize(
    "modulo",
    ["src.agents.mov_factsheet", "src.agents.processo_synthesis", "src.agents.merito_synthesis"],
)
def test_contra_exemplo_os_agentes_do_engine_continuam_existindo(modulo):
    """Espelho exato do teste acima, na direcao oposta.

    Os 3 sao do ENGINE e moram ao lado do que saiu — no mesmo `src/agents/` e no mesmo
    `include_router` de `main.py`. Se um teardown futuro cortar por proximidade, este
    e o teste que fica vermelho. `ModuleNotFoundError` aqui = alguem levou o engine
    junto.
    """
    assert importlib.import_module(modulo) is not None

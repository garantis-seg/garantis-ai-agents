"""Card 869egwv81 — o agente `edital_summarizer` saiu com o produto Licitacao (2026-08-11).

Ele era o 4o repo do teardown, e o unico que ninguem tinha olhado: o card nomeava 2
repos (licitacao-pipeline e execucao-fiscal) e a UI era o 3o. O agente aqui so ficou
visivel quando os DOIS callers dele morreram no mesmo dia — `frontend-api
routers/licitacao_summary.py` (ef#1340) e `whatsapp-bot services/edital_analyzer.py`
(bot#4).

⚠️ A leitura e do payload EXECUTAVEL (`app.routes`), nunca do texto de `main.py`:
o proprio arquivo cita "summarization" na lista de imports vizinha, entao um
`assert "summarization" not in texto` seria fragil pelo motivo errado.

⚠️⚠️ O CONTRA-EXEMPLO NAO E DECORACAO: sem ele, um `app` que falhasse ao montar
qualquer rota satisfaria a assercao de ausencia e o teste passaria verde. Aqui ele
carrega uma 2a funcao — os agentes do ENGINE (mov_factsheet / processo_synthesis /
merito_synthesis) moram no mesmo `main.py` e no mesmo `include_router`; se alguem
"terminar o servico" cortando por proximidade, e por aqui que se ve.
"""

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
        __import__("src.agents.edital_summarizer")


def test_contra_exemplo_os_agentes_do_engine_continuam_montados(rotas_montadas):
    """Sem isto o teste acima passa verde num `app` que nao montou nada."""
    for prefixo in ("/mov-factsheet", "/processo-synthesis", "/merito-synthesis"):
        assert any(p.startswith(prefixo) for p in rotas_montadas), (
            f"as rotas de {prefixo} sumiram — elas sao do ENGINE, nao do produto Licitacao"
        )

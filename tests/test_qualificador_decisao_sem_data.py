"""A decisão sem data e o trecho longo não derrubam a qualificação inteira.

Loop de fichas, rodada 3 (17/11/2026): 13 de 78 fichas saíram sem a qualificação da
S2c. O schema recusou a resposta com HTTP 422 por 1 campo: `decisoes.N.data` nulo (12
fichas) ou `prova.trecho` com mais de 300 caracteres (1 ficha).
"""
from src.agents.qualificador_conexo.schemas import MAX_TRECHO, Decisao, Prova


def test_decisao_provada_sem_data_e_aceita():
    d = Decisao.model_validate({"etapa": "CARF", "resultado": "desfavoravel", "data": None,
                                "prova": {"doc_id": "d1", "pagina": 2, "trecho": "negar provimento"}})
    assert d.data is None and d.resultado == "desfavoravel"


def test_controle_a_data_valida_continua_a_passar():
    d = Decisao.model_validate({"etapa": "CARF", "resultado": "parcial", "data": "2024-12-17"})
    assert d.data == "2024-12-17"


def test_trecho_longo_e_cortado_e_nao_recusado():
    p = Prova.model_validate({"doc_id": "d1", "pagina": 1, "trecho": "a" * (MAX_TRECHO + 80)})
    assert len(p.trecho) == MAX_TRECHO

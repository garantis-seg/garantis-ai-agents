"""CI gate pro prose_lint — pega regressao se alguem mexer no _build_filtro_redacao
e reintroduzir vazamento (espelha tests/test_polo_array_cleanup_sql.py). O linter
operacionaliza a List-B do <filtro_redacao_advogado>; o corpus bom/ruim e o do demo().
"""
from src.agents.merito_synthesis.prose_lint import is_clean, lint, lint_fields


def test_demo_corpus():
    """O par certo/errado do filtro: errado vaza >=5 categorias, certo passa limpo."""
    from src.agents.merito_synthesis import prose_lint
    prose_lint.demo()  # asserts dentro


def test_clean_prose_passes():
    certo = ("A baixa perspectiva de exito das teses, somada a fase recursal sem "
             "decisao definitiva, sustenta um risco no minimo Medio de acionamento. "
             "A apolice foi aceita em Execucao Fiscal suspensa aguardando os Embargos.")
    assert lint(certo) == []
    assert is_clean(certo)


def test_each_listb_category_caught():
    cases = {
        "decimal_score": "o score agregado foi 0.20 no caso",
        "percentual": "chance de 40% de reversao",
        "snake_case": "conforme o campo poucas_chances do mov_id",
        "T_codigo": "aplicou-se o Template T-B1 aqui",
        "literal_bastidor": "a Matriz Daycoval determinou o risco",
        "merito_id_num": "o merito 680128 foi avaliado",
    }
    for expected_cat, txt in cases.items():
        cats = {c for c, _ in lint(txt)}
        assert cats, f"{txt!r} deveria vazar mas passou limpo"


def test_lint_fields_merges():
    viols = lint_fields("texto limpo", "score 0.5", None, "Poletto")
    cats = {c for c, _ in viols}
    assert "decimal_score" in cats
    assert "literal_bastidor" in cats


def test_empty_is_clean():
    assert lint(None) == []
    assert lint("") == []

"""O redator v5 deixa o modelo pensar (CADERNO da ficha, item 65, 13/11/2026).

O Alfredo, dono do produto, decidiu que a ficha vale mais que o custo: o redator
roda no `gemini-3.1-pro-preview`, que pensa por padrão, e a chamada da fase B não
pode mais desligar o raciocínio com `thinking_budget=0`. O teto de saída sobe,
porque o Gemini conta os tokens de raciocínio dentro dele.
"""

from tests import test_ficha_writer_v5 as T


def _fase_b(prov: T._Prov) -> list[dict]:
    return [c for c in prov.chamadas if c["_fase"] == "B"]


def test_a_fase_b_do_redator_nao_desliga_o_raciocinio(monkeypatch):
    prov = T._Prov(T._leituras(), [T._emissao()])
    r = T._rodar(prov, monkeypatch)
    assert r.success, r.erros
    chamadas = _fase_b(prov)
    assert chamadas, "o redator não chamou o modelo na fase B"
    for kw in chamadas:
        assert kw.get("thinking_budget") is None, (
            "a fase B desligou o raciocínio: thinking_budget=%r" % kw.get("thinking_budget"))


def test_a_fase_b_do_redator_tem_teto_de_saida_para_o_raciocinio(monkeypatch):
    prov = T._Prov(T._leituras(), [T._emissao()])
    T._rodar(prov, monkeypatch)
    for kw in _fase_b(prov):
        assert kw.get("max_tokens", 0) >= 32768, kw.get("max_tokens")


def test_o_papel_do_redator_e_o_argon_ou_pensa_por_padrao():
    """Guarda do shared: o redator roda no modelo mais forte do catálogo. Desde
    17/11/2026 (CADERNO, item 68) é o `gemini-4-argon`, que não aceita
    `thinking_config`. Se o papel voltar a um modelo que não é o argon e não
    pensa, este teste avisa antes do deploy. A política é do papel, não do código."""
    from garantis_shared import llm_models

    modelo = llm_models.model_for("ficha_redacao")
    assert modelo == "gemini-4-argon" or llm_models.MODELS[modelo].thinks_by_default, modelo

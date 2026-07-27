"""Cache implicito do Vertex entra no CUSTO, nao so no log.

Contexto (2026-07-27): o preco do gemini-2.5-flash foi corrigido de 0.15/0.60 pra
0.30/2.50 (a fatura sempre cobrou isso). Mas `calculate_cost` nao recebia
`cached_tokens`, entao os ~9,2M tokens que vieram do cache implicito na semana eram
cobrados como input CHEIO: **US$32,10 contra US$29,98 da fatura = ~7% pra CIMA**.
Antes da correcao de preco o erro era 2,15x pra BAIXO — o cache era o unico vetor
que compensava, e corrigir so o preco expos o desvio no outro sentido.

`cached_content_token_count` e SUBCONJUNTO de `prompt_token_count` (nao soma).

Run: pytest tests/test_cached_no_custo.py -q
"""
from __future__ import annotations

import pytest

from src.providers.gemini import GEMINI_PRICING, GeminiProvider


def _p() -> GeminiProvider:
    """Sem tocar rede/credencial — só a aritmética de preço."""
    return GeminiProvider.__new__(GeminiProvider)


def test_cached_cobrado_no_preco_de_cached():
    """1M todo cacheado no 3.1-flash-lite: 0.025, não 0.25."""
    c = _p().calculate_cost("gemini-3.1-flash-lite", 1_000_000, 0, 1_000_000)
    assert c == pytest.approx(0.025)


def test_sem_cached_o_custo_nao_muda():
    """Não-regressão: chamada sem cache custa o mesmo de antes do patch."""
    p = _p()
    assert p.calculate_cost("gemini-3.1-flash-lite", 1_000_000, 0) == pytest.approx(0.25)
    assert p.calculate_cost("gemini-3.1-flash-lite", 1_000_000, 0, 0) == pytest.approx(0.25)


def test_cache_parcial_soma_as_duas_faixas():
    """400k dos 1M vieram do cache."""
    c = _p().calculate_cost("gemini-3.1-flash-lite", 1_000_000, 0, 400_000)
    assert c == pytest.approx(0.6 * 0.25 + 0.4 * 0.025)


def test_cached_nunca_maior_que_o_input():
    """Defensivo: cached é SUBCONJUNTO do prompt. Shape torto do vendor não pode
    gerar billable_input negativo (custo abaixo do real)."""
    c = _p().calculate_cost("gemini-3.1-flash-lite", 1_000, 0, 999_999)
    assert c == pytest.approx(1_000 / 1_000_000 * 0.025)
    assert c > 0


def test_o_caso_que_motivou_o_patch_2_5_flash():
    """Reproduz o desvio no gemini-2.5-flash, semana 2026-07-20..26.

    ⚠️ SEMANTICA que este teste amarra (errei na 1a tentativa): a fatura tem SKUs
    SEPARADOS pra input e pra cache, e `prompt_token_count` do ledger e a SOMA dos
    dois. Provado pelo controle de 07-22: ledger input 5.400.396 == fatura input
    5.240.634 + cached 159.762. Logo o `input_tokens` que chega aqui e 80,86M, nao
    os 71,66M do SKU de input.

    SKUs medidos na semana (billing export, GBP/rate -> USD):
      Text Input     71.662.082 tok @ 0.30  = 21.50
      Input Caching   9.197.578 tok @ 0.03  =  0.28
      Text Output     3.267.960 tok @ 2.50  =  8.17
                                      total = 29.95
    """
    p = _p()
    ledger_input = 71_662_082 + 9_197_578   # = prompt_token_count
    fatura = 21.50 + 0.28 + 8.17            # 29.95

    sem_cache = p.calculate_cost("gemini-2.5-flash", ledger_input, 3_267_960)
    com_cache = p.calculate_cost("gemini-2.5-flash", ledger_input, 3_267_960, 9_197_578)

    assert sem_cache > fatura * 1.07, f"sem cached deveria estourar ~8%: {sem_cache:.2f}"
    assert com_cache == pytest.approx(fatura, rel=0.005), f"com cached: {com_cache:.2f}"
    assert abs(com_cache - fatura) < abs(sem_cache - fatura)


def test_todo_modelo_do_catalogo_tem_cached_per_1m():
    for model, pricing in GEMINI_PRICING.items():
        assert "cached_per_1m" in pricing, model
        # cached nunca é MAIOR que o input (seria desconto negativo).
        assert pricing["cached_per_1m"] <= pricing["input_per_1m"], model


def test_provider_sem_cached_per_1m_cobra_input_cheio():
    """Regra da casa: sem preço de cache declarado, NUNCA inventa desconto.
    Cobre os providers não-Gemini, cujo get_model_pricing não tem a chave."""
    class _Outro(GeminiProvider):
        def get_model_pricing(self, model):  # noqa: ARG002
            return {"input_per_1m": 1.00, "output_per_1m": 2.00}

    c = _Outro.__new__(_Outro).calculate_cost("qualquer", 1_000_000, 0, 1_000_000)
    assert c == pytest.approx(1.00), "sem cached_per_1m deve cobrar input cheio"

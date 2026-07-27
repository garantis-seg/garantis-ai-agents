"""Guarda: preco vem do catalogo unico, e modelo sem preco GRITA.

Contexto (2026-07-27, reconciliacao contra o billing export do GCP): o retorno
silencioso `{"input_per_1m": 0.0, "output_per_1m": 0.0}` pra modelo fora do
catalogo e o mecanismo que esconde gasto. Historico medido:
  * 39.309 calls em 06-26..28 gravaram tokens com cost_usd=0 = US$97,61 fora do ledger
  * reincidiu no gemini-3.5-flash (~US$25/semana, backfillado em 07-24)
  * reincidiu no gemini-3-flash (US$10,93 na semana 07-20..26, ZERO rows)
Tres vezes o MESMO mecanismo. O fix e falhar alto, nao lembrar de conferir.

Run: pytest tests/test_pricing_fail_loud.py -q
"""
from __future__ import annotations

import logging
import os
import re

import pytest

from src.providers.gemini import GEMINI_PRICING, GeminiProvider

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_EDITAL_AGENT = os.path.join(_HERE, "src", "agents", "edital_summarizer", "agent.py")


def _provider() -> GeminiProvider:
    """Instancia sem tocar rede/credencial (so precisamos de get_model_pricing)."""
    return GeminiProvider.__new__(GeminiProvider)


def test_modelo_conhecido_devolve_o_preco_do_catalogo_seja_qual_for():
    """Este repo NAO e dono do VALOR do preco — o catalogo em garantis-shared e, e os
    testes de lah o guardam contra a fatura. Aqui garantimos so o ENDERECO: o que o
    provider devolve e exatamente o que o catalogo diz, sem copia local no meio.
    (Assertar 0.30/2.50 aqui acoplaria este PR ao pin do wheel.)"""
    from garantis_shared.llm_models import cached_price_for, gemini_pricing_pairs

    p = _provider()
    inp, out = gemini_pricing_pairs()["gemini-2.5-flash"]
    assert p.get_model_pricing("gemini-2.5-flash") == {
        "input_per_1m": inp,
        "output_per_1m": out,
        "cached_per_1m": cached_price_for("gemini-2.5-flash"),
    }


def test_catalogo_vem_do_shared_e_nao_de_dict_literal_local():
    """A 3a copia do preco morreu em 2026-07-24 (PR #105) e nao deve voltar: o
    GEMINI_PRICING e DERIVADO de gemini_pricing_pairs(). Pega a forma."""
    from garantis_shared.llm_models import gemini_pricing_pairs

    assert set(GEMINI_PRICING) == set(gemini_pricing_pairs())
    src = open(os.path.join(_HERE, "src", "providers", "gemini.py"), encoding="utf-8").read()
    assert "gemini_pricing_pairs" in src
    # nenhum literal de preco por 1M fora de comentario
    literais = [
        ln for ln in src.splitlines()
        if re.search(r'"(input|output)_per_1m":\s*\d', ln) and not ln.lstrip().startswith("#")
        and "0.0" not in ln  # o fallback de modelo desconhecido pode ser literal
    ]
    assert literais == [], f"preco literal de volta em gemini.py: {literais}"


def test_modelo_desconhecido_grita_e_devolve_zero(caplog):
    p = _provider()
    with caplog.at_level(logging.ERROR):
        out = p.get_model_pricing("gemini-que-nao-existe-7")
    assert out == {"input_per_1m": 0.0, "output_per_1m": 0.0}
    msgs = [r.getMessage() for r in caplog.records]
    assert any("GEMINI_PRICING_MODEL_UNKNOWN" in m for m in msgs), msgs
    assert any("gemini-que-nao-existe-7" in m for m in msgs), msgs


def test_todo_modelo_que_este_repo_pode_servir_tem_preco():
    """Modelo que este repo escolhe por DEFAULT/env tem que existir no catalogo —
    senao o custo dele sai 0. Cobre os defaults locais + os papeis do engine.
    (Modelo faturado que este repo NAO serve e problema do catalogo, guardado lah.)"""
    from garantis_shared.llm_models import ROLES

    from src.providers.gemini import DEFAULT_MODEL

    servidos = {DEFAULT_MODEL} | {
        ROLES[r] for r in ("engine_layer1", "engine_layer2", "engine_layer3",
                           "engine_layer3_v2", "engine_l1_escalate", "vision_fallback")
    }
    faltando = sorted(m for m in servidos if m not in GEMINI_PRICING)
    assert faltando == [], f"modelos servidos sem preco no catalogo: {faltando}"


def test_edital_summarizer_nao_tem_preco_hardcoded():
    """Era a 4a copia do preco (0.15/0.60), fora do catalogo e ERRADA — corrigir o
    catalogo nao corrigia essa linha. Pega a FORMA: nenhum literal de preco por
    1M no arquivo, so leitura do provider."""
    src = open(_EDITAL_AGENT, encoding="utf-8").read()
    hardcoded = [
        ln for ln in src.splitlines()
        if re.search(r"cost_per_1m|per_1m\s*=\s*0\.\d", ln) and not ln.lstrip().startswith("#")
    ]
    assert hardcoded == [], f"preco hardcoded de volta: {hardcoded}"
    assert "llm.get_model_pricing(model)" in src


@pytest.mark.parametrize("bad", ["gemini-2.5-flash-preview", "models/gemini-2.5-flash",
                                 "gemini-2.5-flash-002"])
def test_alias_de_modelo_nao_casa_e_por_isso_grita(bad, caplog):
    """O lookup e por chave EXATA — qualquer sufixo/prefixo zera o preco. Nao vamos
    normalizar (o vendor muda de forma sem avisar); vamos GRITAR."""
    p = _provider()
    with caplog.at_level(logging.ERROR):
        out = p.get_model_pricing(bad)
    assert out["input_per_1m"] == 0.0
    assert any("GEMINI_PRICING_MODEL_UNKNOWN" in r.getMessage() for r in caplog.records)

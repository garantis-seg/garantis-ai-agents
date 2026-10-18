"""O L2 faz UMA LLM call, a synthesis: a call B (probabilidade_exito pela Matriz Daycoval) saiu
na faxina 7 (card 869fcytag).

Ela so rodava com jurisprudencia direcional, e a fonte (jurisprudencias.ai) foi desligada: o gate
de custo EXITO_GATED_ON_JURIS a pulava em todo L2. ⛔ E a guarda de custo do L2: uma call a mais
por processo multiplica o gasto da cascade, e tirar so a flag (sem a call) fazia exatamente isso.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from src.agents.processo_synthesis import agent as l2
from src.agents.processo_synthesis.schemas import (
    MovFactSheetMin,
    ProcessoSynthesisCardRich,
    ProcessoSynthesisRequest,
)


class _Provider:
    """Provider falso: conta as calls e devolve o card que o LLM `emitiu`."""

    def __init__(self, card_do_llm: dict):
        self.calls: list[dict] = []
        self._texto = json.dumps(card_do_llm)

    async def agenerate(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(text=self._texto, input_tokens=10, output_tokens=5,
                               cached_tokens=2, metadata={"cost_usd": 0.01})


def test_o_L2_faz_UMA_call_e_o_card_sai_sem_probabilidade_de_exito(monkeypatch):
    # O campo saiu do response_schema da call. Mesmo que o LLM o emita, o card servido
    # (ProcessoSynthesisCardRich, o tipo da rota) sai com ele vazio.
    prov = _Provider({"processo_numero": "00000000000000000001",
                      "probabilidade_exito": {"classificacao": "provavel", "score": 1.0}})
    monkeypatch.setattr(l2, "create_provider", lambda provider: prov)
    req = ProcessoSynthesisRequest(processo_numero="00000000000000000001",
                                   mov_factsheets=[MovFactSheetMin(mov_id="m1", data="2024-01-01")])

    out = asyncio.run(l2.classify_processo_synthesis(req, model="m", provider="gemini"))

    assert len(prov.calls) == 1, [c.get("response_schema") for c in prov.calls]
    assert prov.calls[0]["response_schema"] is l2.ProcessoSynthesisCard
    assert "probabilidade_exito" not in l2.ProcessoSynthesisCard.model_fields
    servido = ProcessoSynthesisCardRich(**out["card"]).model_dump()
    assert servido["probabilidade_exito"]["classificacao"] is None, servido
    assert set(out["raw_response"]) == {"synthesis"} == set(out["llm_raw_prompt"])
    assert out["usage"]["calls"] == 1
    assert (out["usage"]["total_tokens"], out["usage"]["cost_usd"]) == (15, 0.01)

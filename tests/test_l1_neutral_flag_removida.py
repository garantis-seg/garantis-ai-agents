"""O L1 roda sempre o caminho v4: a flag `L1_NEUTRAL_ENABLED` e o ramo v3.1 sairam.

A flag valia true em todos os runtimes, entao o ramo v3.1 nao rodava em lugar nenhum.
O teste liga a env morta em OFF e confere que o agent segue no prompt v4, no
`response_schema` v4 e no rotulo v4 da telemetria.
"""
from __future__ import annotations

import asyncio

import pytest


@pytest.mark.parametrize("env", ["false", "true", None])
def test_o_agent_usa_o_v4_com_a_env_morta_em_qualquer_valor(monkeypatch, env):
    from src.agents.mov_factsheet import agent as A
    from src.agents.mov_factsheet.schemas_v4 import MovFactSheetCardV4

    visto: dict = {}

    async def _fake_fallback(provider, **kw):
        visto.update(kw)

        class _R:
            text = '{"tipo_doc":"despacho","relevancia_merito":"baixa","resumo_ato":"x"}'
            input_tokens = output_tokens = 1
            metadata = {"model_variant": "text"}

        return _R()

    monkeypatch.setattr(A, "call_l1_with_vision_fallback", _fake_fallback)
    monkeypatch.setattr(A, "create_provider", lambda p: object())
    if env is None:
        monkeypatch.delenv("L1_NEUTRAL_ENABLED", raising=False)
    else:
        monkeypatch.setenv("L1_NEUTRAL_ENABLED", env)

    out = asyncio.run(A.classify_mov_factsheet(
        processo={"cnj": "01688863120164025101"},
        mov={"mov_id": "11111111-1111-1111-1111-111111111111", "texto": "Despacho de mero expediente."},
    ))

    assert visto["response_schema"] is MovFactSheetCardV4
    assert "FATOS NEUTROS" in visto["prompt"]
    assert out["prompt_version"].startswith("mov_factsheet.v4.5+")
    assert "error" not in out["card"]

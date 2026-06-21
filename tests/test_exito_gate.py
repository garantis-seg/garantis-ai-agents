"""§3.1 exito-gate (flag EXITO_GATED_ON_JURIS): pula a call B de probabilidade_exito
quando NAO ha sinal de jurisprudencia. Default OFF (byte-identical).

Testa as 2 funcoes de decisao (puras). A integracao (gather vs call unica) depende
do provider LLM — coberta por smoke, nao aqui.
"""
import os

from src.agents.processo_synthesis.agent import _exito_gate_enabled, _juris_has_signal
from src.agents.processo_synthesis.schemas import (
    JurisprudenciaExternaMin,
    ProcessoSynthesisRequest,
)


def _req(je):
    return ProcessoSynthesisRequest(
        processo_numero="0001234-56.2020.8.26.0100",
        tipo_judicial="fiscal",
        mov_factsheets=[],
        jurisprudencia_externa=je,
    )


def test_gate_flag_default_off(monkeypatch):
    monkeypatch.delenv("EXITO_GATED_ON_JURIS", raising=False)
    assert _exito_gate_enabled() is False
    for v in ("true", "1", "yes", "ON", "True"):
        monkeypatch.setenv("EXITO_GATED_ON_JURIS", v)
        assert _exito_gate_enabled() is True
    for v in ("", "false", "0", "off", "no"):
        monkeypatch.setenv("EXITO_GATED_ON_JURIS", v)
        assert _exito_gate_enabled() is False


def test_juris_signal_none_or_indeterminado_is_no_signal():
    assert _juris_has_signal(_req(None)) is False
    assert _juris_has_signal(_req(JurisprudenciaExternaMin(resultado_majoritario="indeterminado"))) is False
    assert _juris_has_signal(_req(JurisprudenciaExternaMin(resultado_majoritario=None))) is False
    assert _juris_has_signal(_req(JurisprudenciaExternaMin(resultado_majoritario=""))) is False


def test_juris_signal_directional_is_signal():
    for rm in ("pro_contribuinte", "pro_fazenda", "dividida"):
        assert _juris_has_signal(_req(JurisprudenciaExternaMin(resultado_majoritario=rm))) is True


if __name__ == "__main__":
    # roda sem pytest: stub minimo de monkeypatch
    class _MP:
        def setenv(self, k, v): os.environ[k] = v
        def delenv(self, k, raising=True): os.environ.pop(k, None)
    test_gate_flag_default_off(_MP())
    test_juris_signal_none_or_indeterminado_is_no_signal()
    test_juris_signal_directional_is_signal()
    print("ok")

"""Captura de finish_reason no provider Gemini (2026-06-21).

O provider ignorava finish_reason — quando o Gemini termina anormal (SAFETY/
RECITATION/...) o response.text vem PARCIAL e o L1 só via 'JSONDecodeError char N'
sem a causa. Agora captura + loga (GEMINI_ABNORMAL_FINISH) + expõe em metadata.
"""
import logging
from types import SimpleNamespace

from src.providers.gemini import _gemini_finish_reason, _gemini_text_and_finish


def _resp(text="{}", finish="STOP", raises=False):
    cand = SimpleNamespace(finish_reason=SimpleNamespace(name=finish), safety_ratings=None)

    class R:
        candidates = [cand]
        prompt_feedback = None

        @property
        def text(self):
            if raises:
                raise ValueError("response blocked")
            return text

    return R()


def test_finish_stop_normal():
    text, fr = _gemini_text_and_finish(_resp(text='{"ok":1}', finish="STOP"), "m")
    assert fr == "STOP" and text == '{"ok":1}'


def test_finish_abnormal_logs(caplog):
    with caplog.at_level(logging.WARNING):
        text, fr = _gemini_text_and_finish(_resp(text='{"resumo_ato":"', finish="SAFETY"), "m")
    assert fr == "SAFETY"
    assert "GEMINI_ABNORMAL_FINISH" in caplog.text  # causa fica visível/grepável


def test_text_raises_returns_empty(caplog):
    with caplog.at_level(logging.WARNING):
        text, fr = _gemini_text_and_finish(_resp(raises=True, finish="SAFETY"), "m")
    assert text == ""
    assert "GEMINI_RESPONSE_TEXT_RAISED" in caplog.text


def test_finish_reason_none_when_no_candidates():
    class R:
        candidates = []

    assert _gemini_finish_reason(R()) is None

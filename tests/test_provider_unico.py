"""`create_provider`: só o Gemini, um por processo. Outro nome é erro de quem chamou."""
import pytest

import src.providers.factory as F
import src.providers.gemini as G


class _Duble:
    criados = 0

    def __init__(self):
        _Duble.criados += 1


@pytest.fixture
def duble(monkeypatch):
    _Duble.criados = 0
    monkeypatch.setattr(G, "GeminiProvider", _Duble)
    monkeypatch.setattr(F, "_gemini", None)
    return _Duble


@pytest.mark.parametrize("nome", [None, "gemini", "Gemini"])
def test_o_nome_do_gemini_devolve_o_mesmo_provider(duble, nome):
    primeiro = F.create_provider(nome)
    assert isinstance(primeiro, duble)
    assert F.create_provider(nome) is primeiro, "recriar o provider recria o pool"
    assert duble.criados == 1


@pytest.mark.parametrize("nome", ["openai", ""])
def test_outro_nome_e_erro(duble, nome):
    with pytest.raises(ValueError, match="Unsupported provider"):
        F.create_provider(nome)
    assert duble.criados == 0


@pytest.mark.parametrize("nome", [None, ""])
def test_o_indexador_sem_nome_usa_o_gemini(duble, nome):
    """O request do indexador traz `provider` opcional: vazio vale o Gemini, nunca o erro."""
    from src.agents.doc_indexer.agent import _provider

    assert isinstance(_provider(nome), duble)


def test_falha_ao_construir_vira_RuntimeError(monkeypatch):
    def explode():
        raise OSError("sem rede")

    monkeypatch.setattr(G, "GeminiProvider", explode)
    monkeypatch.setattr(F, "_gemini", None)
    with pytest.raises(RuntimeError, match="Failed to initialize gemini provider"):
        F.create_provider()

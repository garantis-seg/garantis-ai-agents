"""O modelo de cada agent sai do PAPEL no registro do shared (`model_for`), e env
de modelo nao muda nada: env era uma 2a fonte, e divergia do papel em silencio
(deixou o auditor de evidencias num modelo que aposenta e o par redator x auditor
de texto invertido em relacao ao registro).
"""
import importlib

import pytest
from garantis_shared.llm_models import model_for

import src.agents.auditor_evidencias.agent as auditor_evidencias
import src.agents.auditor_evidencias.verificador as verificador
import src.agents.auditor_ficha.agent as auditor_ficha
import src.agents.calculo_ficha.agent as calculo_ficha
import src.agents.ficha_writer.agent as ficha_writer
from src.providers.gemini import DEFAULT_MODEL as DEFAULT_DO_PROVIDER

_PAPEIS = [
    (calculo_ficha, "ficha_calculo"),
    (auditor_evidencias, "ficha_auditoria_evidencias"),
    (verificador, "ficha_auditoria_evidencias"),
    (ficha_writer, "ficha_redacao"),
    (auditor_ficha, "ficha_auditoria_texto"),
]

#: As envs de modelo que estes agents ja leram. Hostis: se alguma voltar a ser
#: lida, o modulo recarregado sai do papel e o teste quebra.
_ENVS_DE_MODELO = (
    "DEFAULT_MODEL", "CALCULO_FICHA_MODEL", "AUDITOR_EVIDENCIAS_MODEL",
    "FICHA_WRITER_MODEL", "FICHA_AUDITORIA_TEXTO_MODEL",
)


def _recarregar_sob_env_hostil(mod, monkeypatch) -> str:
    try:
        with monkeypatch.context() as m:
            for env in _ENVS_DE_MODELO:
                m.setenv(env, "gemini-hostil-9")
            return importlib.reload(mod).DEFAULT_MODEL
    finally:
        # O reload REBINDA o modulo que outros testes monkeypatcham: recarrega de
        # novo sob o env original, senao a ordem dos testes vira dependencia.
        importlib.reload(mod)


@pytest.mark.parametrize(("mod", "papel"), _PAPEIS,
                         ids=[m.__name__.split("agents.")[1] for m, _ in _PAPEIS])
def test_agent_roda_o_modelo_do_papel_mesmo_com_env_de_modelo(monkeypatch, mod, papel):
    assert _recarregar_sob_env_hostil(mod, monkeypatch) == model_for(papel)


def test_controle_positivo_o_reload_enxerga_env(monkeypatch, tmp_path):
    """Sem isto, um reload que nao enxergasse env passaria o teste acima calado."""
    (tmp_path / "le_env_de_modelo.py").write_text(
        'import os\nDEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "papel")\n', encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    mod = importlib.import_module("le_env_de_modelo")
    assert _recarregar_sob_env_hostil(mod, monkeypatch) == "gemini-hostil-9"


def test_auditor_e_auditado_rodam_modelos_diferentes():
    """ANTI-CONLUIO no que RODA (o registro guarda o mesmo nos papeis): auditar com
    o modelo que produziu e revisar o proprio trabalho — os erros se confirmam."""
    assert calculo_ficha.DEFAULT_MODEL != auditor_evidencias.DEFAULT_MODEL
    assert calculo_ficha.DEFAULT_MODEL != verificador.DEFAULT_MODEL
    assert ficha_writer.DEFAULT_MODEL != auditor_ficha.DEFAULT_MODEL


def test_default_do_provider_vem_do_registro():
    assert DEFAULT_DO_PROVIDER == model_for("engine_layer1")

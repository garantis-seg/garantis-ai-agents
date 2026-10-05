"""O modelo de cada agent da ficha sai do SEU papel no registro do shared
(`model_for`): nem literal, nem env, nem o papel de outro agent. Env de modelo era
uma 2a fonte e divergia do papel em silencio (deixou o auditor de evidencias num
modelo que aposenta e o par redator x auditor de texto invertido em relacao ao
registro).
"""
import ast
import importlib
import inspect

import pytest
from garantis_shared import llm_models
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
_IDS = [m.__name__.split("agents.")[1] for m, _ in _PAPEIS]


@pytest.mark.parametrize(("mod", "papel"), _PAPEIS, ids=_IDS)
def test_agent_le_o_SEU_papel(monkeypatch, mod, papel):
    """Com um valor-sentinela por papel, o modulo recarregado so acerta lendo o
    proprio papel: literal, env ou o papel de OUTRO agent dao outro valor. Com os
    valores reais nao daria — so ha dois modelos centrais, entao o papel errado
    quase sempre tem o mesmo valor."""
    monkeypatch.setattr(llm_models, "ROLES", {r: f"sentinela-{r}" for r in llm_models.ROLES})
    try:
        assert importlib.reload(mod).DEFAULT_MODEL == f"sentinela-{papel}"
    finally:
        monkeypatch.undo()
        # O reload REBINDA o modulo que outros testes monkeypatcham: recarrega sob o
        # registro real, senao a ordem dos testes vira dependencia.
        importlib.reload(mod)


_LEITORES_DE_ENV = {"os.getenv", "getenv", "os.environ.get", "environ.get"}


def _envs_de_modelo_lidas(fonte: str) -> list[str]:
    """Nomes de env com MODEL lidos por os.getenv / os.environ.get / os.environ[...]."""
    achados = []
    for no in ast.walk(ast.parse(fonte)):
        if isinstance(no, ast.Call) and no.args and ast.unparse(no.func) in _LEITORES_DE_ENV:
            alvo = no.args[0]
        elif isinstance(no, ast.Subscript) and ast.unparse(no.value) in {"os.environ", "environ"}:
            alvo = no.slice
        else:
            continue
        if isinstance(alvo, ast.Constant) and isinstance(alvo.value, str) and "MODEL" in alvo.value:
            achados.append(alvo.value)
    return sorted(achados)


@pytest.mark.parametrize(("mod", "papel"), _PAPEIS, ids=_IDS)
def test_agent_nao_le_env_de_modelo(mod, papel):
    """Nem no import nem na chamada: o teste do papel acima so ve o import."""
    assert _envs_de_modelo_lidas(inspect.getsource(mod)) == []


def test_controle_positivo_o_detector_enxerga_import_e_chamada():
    fonte = (
        'import os\n'
        'A = os.getenv("CALCULO_FICHA_MODEL", "x")\n'
        'def f(model=None):\n'
        '    return model or os.environ.get("AUDITOR_EVIDENCIAS_MODEL") or os.environ["DEFAULT_MODEL"]\n'
        'P = os.getenv("DEFAULT_PROVIDER", "gemini")\n'
    )
    assert _envs_de_modelo_lidas(fonte) == [
        "AUDITOR_EVIDENCIAS_MODEL", "CALCULO_FICHA_MODEL", "DEFAULT_MODEL"]


def test_auditor_e_auditado_rodam_modelos_diferentes():
    """ANTI-CONLUIO no que RODA (o registro guarda o mesmo nos papeis): auditar com
    o modelo que produziu e revisar o proprio trabalho — os erros se confirmam."""
    assert calculo_ficha.DEFAULT_MODEL != auditor_evidencias.DEFAULT_MODEL
    assert calculo_ficha.DEFAULT_MODEL != verificador.DEFAULT_MODEL
    assert ficha_writer.DEFAULT_MODEL != auditor_ficha.DEFAULT_MODEL


def test_default_do_provider_vem_do_registro():
    assert DEFAULT_DO_PROVIDER == model_for("engine_layer1")

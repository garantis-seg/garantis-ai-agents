"""O modelo de cada agent sai do SEU papel no registro do shared (`model_for`): nem
literal, nem env, nem o papel de outro agent. Env de modelo era uma 2a fonte e divergia
do papel em silencio (deixou o auditor de evidencias num modelo que aposenta e o par
redator x auditor de texto invertido em relacao ao registro).
"""
import ast
import inspect
from pathlib import Path

import pytest
from garantis_shared.llm_models_guarda import modelos_escritos_a_mao

import src.agents.apolice_lifecycle.agent as apolice_lifecycle
import src.agents.auditor_evidencias.agent as auditor_evidencias
import src.agents.auditor_evidencias.verificador as verificador
import src.agents.auditor_ficha.agent as auditor_ficha
import src.agents.calculo_ficha.agent as calculo_ficha
import src.agents.ficha_writer.agent as ficha_writer
import src.agents.merito_reducao_v2.agent as merito_reducao_v2
import src.agents.merito_synthesis.agent as merito_synthesis
import src.agents.merito_synthesis.redacao as merito_redacao
import src.agents.mov_factsheet.agent as mov_factsheet
import src.agents.mov_triage.agent as mov_triage
import src.agents.peticao_confirmador.agent as peticao_confirmador
import src.agents.processo_synthesis.agent as processo_synthesis
import src.providers.gemini as provider_gemini

_PAPEIS = [
    (calculo_ficha, "ficha_calculo"),
    (auditor_evidencias, "ficha_auditoria_evidencias"),
    (verificador, "ficha_auditoria_evidencias"),
    (ficha_writer, "ficha_redacao"),
    (auditor_ficha, "ficha_auditoria_texto"),
    (mov_triage, "engine_layer1"),
    (mov_factsheet, "engine_layer1"),
    (processo_synthesis, "engine_layer2"),
    (merito_synthesis, "engine_layer3"),
    (merito_redacao, "engine_layer3"),
    (merito_reducao_v2, "engine_layer3_v2"),
    (peticao_confirmador, "peticao_confirmador"),
    (apolice_lifecycle, "apolice_ciclo_de_vida"),
    # so alcancado por quem nao passa modelo (test_connection, /providers)
    (provider_gemini, "engine_layer1"),
]
_IDS = [m.__name__.removeprefix("src.") for m, _ in _PAPEIS]


@pytest.mark.parametrize(("mod", "papel"), _PAPEIS, ids=_IDS)
def test_agent_le_o_SEU_papel(mod, papel):
    """O `DEFAULT_MODEL` e EXATAMENTE `model_for('<o papel dele>')`. Comparar pelo VALOR
    nao serviria: so ha dois modelos centrais, entao o papel errado quase sempre da o
    mesmo valor. Literal, env com o papel de default ou papel alheio mudam a expressao."""
    [atribuicao] = [
        no for no in ast.parse(inspect.getsource(mod)).body
        if isinstance(no, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "DEFAULT_MODEL" for t in no.targets)
    ]
    assert ast.unparse(atribuicao.value) == f"model_for('{papel}')"


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
    """Nem no import nem na chamada: o teste do papel acima so ve a expressao do topo."""
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


def test_nenhum_modelo_escrito_a_mao_no_repo():
    """A guarda do shared sobre o repo inteiro: codigo e deploy (cloudbuild) so
    escolhem modelo pelo papel. Comentario, docstring e teste podem citar modelo."""
    assert modelos_escritos_a_mao(Path(__file__).resolve().parents[1]) == []


def test_controle_positivo_a_guarda_ve_o_que_este_repo_escreve(tmp_path):
    (tmp_path / "agent.py").write_text('DEFAULT_MODEL = "gemini-2.5-flash"\n', encoding="utf-8")
    (tmp_path / "cloudbuild-deploy.yaml").write_text(
        "      - 'X=1,MOV_TRIAGE_MODEL=gemini-3.1-flash-lite'\n", encoding="utf-8")
    assert modelos_escritos_a_mao(tmp_path) == [
        "agent.py:1: gemini-2.5-flash",
        "cloudbuild-deploy.yaml:1: gemini-3.1-flash-lite",
    ]

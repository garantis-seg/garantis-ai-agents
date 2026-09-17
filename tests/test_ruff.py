"""`ruff check` com a config do repo roda DENTRO da suite — e a suite e o gate do deploy.

Ate 2026-09-17 o `pyproject.toml` selecionava regras de lint e NENHUM step as rodava:
config sem executor, 60 violacoes acumuladas (entre elas um F821 real — nome sem
import numa anotacao de `merito_synthesis/prompts.py`). Um step novo no cloudbuild
seria mais um lugar pra esquecer; a suite ja e o runner fail-closed (o `kaniko-build`
tem `waitFor: ['unit-tests']`), entao o lint entra como TESTE.

⛔ Ruff AUSENTE REPROVA, nunca `skip`: um gate que pula quando a ferramenta falta fica
verde para sempre no ambiente em que ninguem a instalou — que e exatamente o container
do step `unit-tests`, se alguem tirar o `ruff` da linha de `pip install` dele.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

_RAIZ = Path(__file__).resolve().parent.parent


def _ruff(*args: str, cwd: Path = _RAIZ) -> subprocess.CompletedProcess:
    if importlib.util.find_spec("ruff") is None:
        pytest.fail(
            "ruff nao esta instalado neste interpretador — o lint e GATE, nao opcional. "
            "O step `unit-tests` do cloudbuild-deploy.yaml instala a versao pinada; "
            "local: `pip install -e \".[dev]\"`."
        )
    return subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--no-cache",
         "--config", str(_RAIZ / "pyproject.toml"), *args],
        cwd=cwd, capture_output=True, text=True, encoding="utf-8",
    )


def test_ruff_limpo_com_a_config_do_repo():
    r = _ruff(".")
    assert r.returncode == 0, (
        "ruff check reprovou com a config do pyproject.toml:\n" + r.stdout + r.stderr
    )


def test_controle_negativo_o_gate_ENXERGA_violacao(tmp_path: Path):
    """⭐ Sem isto, uma config que nao seleciona nada (ou um `exclude` largo demais)
    deixaria o teste de cima verde para sempre. Planta um F821 (o defeito real que o
    lint achou) e um F401 num arquivo fora do repo, com a MESMA config."""
    alvo = tmp_path / "plantado.py"
    alvo.write_text("import os\n\n\ndef f(x: \"NaoImportado\") -> None:\n    pass\n",
                    encoding="utf-8")
    r = _ruff(str(alvo), cwd=tmp_path)
    assert r.returncode != 0, "o gate nao enxergou violacao plantada:\n" + r.stdout
    assert "F821" in r.stdout and "F401" in r.stdout, r.stdout

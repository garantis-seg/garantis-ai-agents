"""O auditor de ficha (S6) atende só o corpo com `nucleo` e `indice_navegavel`.

O shared manda os 2 sempre: a S6 do workflow e o executor local somam o núcleo e
o índice da S4 ao pedido. O corpo sem eles era o auditor v2, e o corpo com
`ficha_json` e `tipo` era o v1. Os 2 caminhos saíram. Um corpo velho recebe 422,
e o cliente do shared grava a ficha como "não auditada", com `erro_contrato`.

Cada gate tem controle positivo: o corpo do shared passa, e o scanner de símbolo
acha o que tem de existir e o que foi plantado.
"""
from __future__ import annotations

import ast
import importlib.util
import inspect
import pathlib
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

import src.agents.auditor_ficha.agent as agent_mod
import src.agents.auditor_ficha.agent_v3 as v3_mod
import src.agents.auditor_ficha.prompts as prompts_mod
from src.agents.auditor_ficha.schemas import AuditarFichaRequest, AuditarFichaResponse
from src.api.routes.auditor_ficha import router
from tests.test_auditor_ficha_v3 import _body

# ── O corpo que o shared monta ──────────────────────────────────────────────


def _chaves_do_shared() -> tuple[str, ...]:
    """`CHAVES_REQUEST_V2` do wheel pinado, lida por AST: o import do pacote puxa o dbos.

    Limite: o wheel e o do pin deste repo, nao o do worker que chama a S6. Uma chave nova
    no shared so entra neste teste depois do bump do pin aqui. Sem o bump, o
    `extra="forbid"` recusa a chave nova e toda S6 sai "nao auditada".
    """
    spec = importlib.util.find_spec("garantis_shared")
    assert spec is not None and spec.origin
    fonte = pathlib.Path(spec.origin).parent / "fichas" / "auditor_ficha.py"
    for no in ast.walk(ast.parse(fonte.read_text(encoding="utf-8"))):
        alvos = ([no.target] if isinstance(no, ast.AnnAssign)
                 else no.targets if isinstance(no, ast.Assign) else [])
        if any(getattr(t, "id", None) == "CHAVES_REQUEST_V2" for t in alvos):
            return tuple(ast.literal_eval(no.value))
    raise AssertionError(f"CHAVES_REQUEST_V2 não está em {fonte}")


def _corpo_do_shared() -> dict[str, Any]:
    """O corpo da S6 do shared: o `dossie` vai como objeto, o relatório da S5 como lista."""
    completo = {
        **_body(),
        "dossie": {"processo": {"numero": "16327.721182/2019-21"},
                   "ultima_decisao": {"acordao": "3102-004.203"}},
        "relatorio_s5": [{"id": "A31", "nivel": "aviso", "campo": "bullets[0]",
                          "mensagem": "bullet longo"}],
        "licoes": ["Confira a data da sessão, não a da publicação."],
    }
    chaves = _chaves_do_shared()
    faltam = set(chaves) - set(completo)
    assert not faltam, f"o shared manda chave que este teste não monta: {sorted(faltam)}"
    return {k: completo[k] for k in chaves}


def test_controle_o_scanner_le_as_chaves_do_shared():
    chaves = _chaves_do_shared()
    assert {"ficha", "dossie", "nucleo", "indice_navegavel", "trilha_leitura"} <= set(chaves)
    assert "gabarito" not in chaves


def test_corpo_do_shared_valida_e_o_dossie_objeto_vira_texto():
    req = AuditarFichaRequest(**_corpo_do_shared())
    assert req.nucleo is not None and req.indice_navegavel is not None
    assert isinstance(req.dossie, str) and "3102-004.203" in req.dossie
    assert [a.id for a in req.relatorio_s5] == ["A31"]


# ── A rota recusa o corpo sem núcleo ou índice ──────────────────────────────


def _sem(*chaves: str) -> dict[str, Any]:
    return {k: v for k, v in _corpo_do_shared().items() if k not in chaves}


@pytest.fixture
def cliente(monkeypatch):
    chamadas: list[AuditarFichaRequest] = []

    async def v3_duble(request, provider, model=None, **_kw):
        chamadas.append(request)
        return AuditarFichaResponse(success=True, veredito="aprovada", aprovado=True,
                                    auditor_enabled=True, prompt_version="auditor_ficha_v3+x")

    def sem_llm(*_a, **_k):
        raise AssertionError("o teste não chama LLM")

    monkeypatch.setattr(v3_mod, "auditar_ficha_v3", v3_duble)
    monkeypatch.setattr(agent_mod, "auditar_ficha_v3", v3_duble, raising=False)
    monkeypatch.setattr(agent_mod, "create_provider", sem_llm, raising=False)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app), chamadas


def test_controle_o_corpo_do_shared_chega_ao_v3(cliente):
    cli, chamadas = cliente
    resp = cli.post("/ficha/auditar", json=_corpo_do_shared())
    assert resp.status_code == 200, resp.text
    assert resp.json()["veredito"] == "aprovada"
    assert len(chamadas) == 1 and chamadas[0].nucleo is not None


@pytest.mark.parametrize("tirar", [
    ("nucleo", "indice_navegavel", "trilha_leitura"),
    ("nucleo", "indice_navegavel"),
    ("nucleo",),
    ("indice_navegavel",),
], ids=["corpo_v2", "so_trilha", "sem_nucleo", "sem_indice"])
def test_corpo_sem_nucleo_ou_indice_e_422(cliente, tirar):
    cli, chamadas = cliente
    resp = cli.post("/ficha/auditar", json=_sem(*tirar))
    assert resp.status_code == 422, resp.text
    assert "nucleo" in resp.text and "indice_navegavel" in resp.text
    assert chamadas == []


@pytest.mark.parametrize("velha,nova", [("ficha_json", "ficha"), ("tipo", "tipo_ficha")])
def test_chave_do_formato_v1_e_422(cliente, velha, nova):
    cli, chamadas = cliente
    corpo = _corpo_do_shared()
    corpo[velha] = corpo.pop(nova)
    resp = cli.post("/ficha/auditar", json=corpo)
    assert resp.status_code == 422, resp.text
    assert velha in resp.text
    assert chamadas == []
    with pytest.raises(ValidationError):
        AuditarFichaRequest(**corpo)


# ── Os símbolos do v2 não voltam ────────────────────────────────────────────

#: O que só o v2 usava. A volta de um deles é a volta do caminho sem núcleo.
_SO_DO_V2 = {
    agent_mod: ("validar_saida", "_normalizar_baldes", "build_auditar_ficha_prompt"),
    prompts_mod: ("build_auditar_ficha_prompt", "_build_output_shape",
                  "_build_gabarito_block", "PROMPT_VERSION"),
}

#: O que o v3 importa destes módulos. O scanner tem de achar cada um.
_DO_V3 = {
    agent_mod: ("calcular_veredito", "erros_de_alertas", "_ancorar", "_falha", "_pendencias",
                "MAX_RODADAS", "DEFAULT_MODEL"),
    prompts_mod: ("build_prompt_de_correcao", "_build_regra_de_decisao", "_fence",
                  "_build_checklist", "_build_baldes"),
}


def _nomes(fonte: str) -> set[str]:
    """Os nomes que o módulo define (def, class, atribuição) ou cita."""
    out: set[str] = set()
    for no in ast.walk(ast.parse(fonte)):
        if isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(no.name)
        elif isinstance(no, ast.Name):
            out.add(no.id)
        elif isinstance(no, ast.alias):
            out.add(no.asname or no.name)
    return out


def test_controle_o_scanner_acha_o_que_o_v3_usa():
    for mod, nomes in _DO_V3.items():
        achados = _nomes(inspect.getsource(mod))
        assert set(nomes) <= achados, (mod.__name__, sorted(set(nomes) - achados))


def test_controle_o_scanner_acha_simbolo_plantado():
    plantado = "from .prompts import PROMPT_VERSION\n\ndef validar_saida():\n    return 1\n"
    assert {"validar_saida", "PROMPT_VERSION"} <= _nomes(plantado)


def test_os_simbolos_do_v2_sairam():
    for mod, nomes in _SO_DO_V2.items():
        sobra = set(nomes) & _nomes(inspect.getsource(mod))
        assert not sobra, (mod.__name__, sorted(sobra))

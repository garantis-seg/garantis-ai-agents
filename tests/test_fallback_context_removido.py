"""O `fallback_context` saiu do request do L1 (mov-factsheet e triagem).

O prompt v4 e o da triagem recebiam o bloco e nao o usavam. O shared no ar pode
seguir mandando a chave ate o bump do wheel: o request ignora chave extra, e esse
e o contrato que torna as 2 ordens de deploy seguras.
"""
from __future__ import annotations

import importlib

import pytest

_LEGADO = {
    "processo": {"cnj": "01688863120164025101"},
    "mov": {"mov_id": "m1", "texto": "Despacho."},
    "documentos_anexados": [],
    "fallback_context": {"processo_resumo_ia": "resumo", "mov_anterior_resumo": None},
}


@pytest.mark.parametrize("modulo,classe", [
    ("src.agents.mov_factsheet.schemas", "MovFactSheetRequest"),
    ("src.agents.mov_triage.schemas", "TriageRequest"),
])
def test_o_request_aceita_o_payload_do_shared_antigo(modulo, classe):
    modelo = getattr(importlib.import_module(modulo), classe)
    req = modelo(**_LEGADO)
    assert "fallback_context" not in modelo.model_fields
    assert "fallback_context" not in req.model_dump()


@pytest.mark.parametrize("modulo", [
    "src.agents.mov_factsheet.schemas",
    "src.agents.mov_triage.schemas",
    "src.agents.mov_factsheet",
    "src.agents.mov_triage",
])
def test_a_classe_FallbackContext_saiu(modulo):
    m = importlib.import_module(modulo)
    assert not hasattr(m, "FallbackContext")
    # Controle positivo: o leitor de atributo acha o vizinho que fica.
    assert hasattr(m, "DocAnexado")

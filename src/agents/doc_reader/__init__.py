"""Leitor de documento — 1 documento, janela isolada, citação por ID (onda 4).

Ver `agent.py`. Papel L do desenho do Agente Investigador (§2): recebe o
`DocumentoIndexado` inteiro daquele documento e nada mais, e devolve envelope
com `confianca` + `objeto_da_confianca` em CAMPO (§5.3).
"""
from .agent import (
    ERRO_CITACAO_INEXISTENTE,
    ERRO_DOC_INVALIDO,
    ERRO_DOC_MUDOU,
    ERRO_ENVELOPE_SEM_CONFIANCA,
    ERRO_PARSE,
    ERRO_SEM_CITACAO,
    PAPEL_LEITOR,
    modelo_leitor,
    perguntar,
    resumir,
)
from .schemas import (
    EvidenciaResumo,
    PerguntarRequest,
    PerguntarResponse,
    ResumirRequest,
    ResumirResponse,
)

__all__ = [
    "ERRO_CITACAO_INEXISTENTE",
    "ERRO_DOC_INVALIDO",
    "ERRO_DOC_MUDOU",
    "ERRO_ENVELOPE_SEM_CONFIANCA",
    "ERRO_PARSE",
    "ERRO_SEM_CITACAO",
    "PAPEL_LEITOR",
    "EvidenciaResumo",
    "PerguntarRequest",
    "PerguntarResponse",
    "ResumirRequest",
    "ResumirResponse",
    "modelo_leitor",
    "perguntar",
    "resumir",
]

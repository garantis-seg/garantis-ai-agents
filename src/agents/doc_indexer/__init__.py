"""Indexador de documento — PDF → `DocumentoIndexado` (onda 2 do Investigador).

Código determinístico + no máximo 1 chamada de OCR. Ver `agent.py`.
"""
from .agent import FLAG_DOC_INDEXER, indexar, montar_documento_indexado
from .schemas import IndexarRequest, IndexarResponse

__all__ = [
    "FLAG_DOC_INDEXER",
    "IndexarRequest",
    "IndexarResponse",
    "indexar",
    "montar_documento_indexado",
]

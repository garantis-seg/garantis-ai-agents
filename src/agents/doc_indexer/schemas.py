"""Contrato de wire do `/doc-indexer/indexar`.

Envelope da casa (`{success, …, model, cost_usd}`): falha de leitura/validação
devolve `success=false` com **HTTP 200** — quem decide o que fazer é o step S2b
do workflow, não o servidor HTTP. 500 fica só para falha inesperada de infra,
como já documenta `src/api/routes/calculo_ficha.py`.

O `documento_indexado` viaja como `dict` puro (o `to_dict()` do shared), não
como modelo Pydantic espelhado. É deliberado: o contrato do `DocumentoIndexado`
mora em **um** lugar (`garantis_shared.calculo_fichas.documento`) e o
`from_dict` de lá é quem valida na chegada. Um espelho Pydantic aqui seria uma
segunda definição da mesma estrutura, e as duas divergiriam no primeiro campo
novo — que é exatamente o que o `test_contrato_doc_indexer` (§9.3) existe para
impedir.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class IndexarRequest(BaseModel):
    """`{doc_id, gcs_path | pdf_base64, doc_hash?, force?}`.

    Duas fontes de bytes porque os dois callers são reais e diferentes: o step
    S2b passa `gcs_path` (o PDF já está no bucket e baixá-lo é trabalho do
    indexador, com o semáforo da casa); teste, eval e reindexação manual passam
    `pdf_base64` sem inventar um objeto no GCS.

    `doc_hash`, quando enviado, é o ponteiro CONGELADO no `/start` (§1.6) e este
    serviço o **confere** contra os bytes que baixou. Divergência ⇒
    `documento_mudou_apos_congelamento`, que é a resposta certa: ler
    silenciosamente outro documento é o modo de falha caro.
    """

    doc_id: str = Field(description="Identidade do ItemDoc (#347) — a MESMA das duas fases")
    gcs_path: Optional[str] = Field(default=None, description="gs://bucket/path do PDF")
    pdf_base64: Optional[str] = Field(default=None, description="PDF em base64 (alternativa ao GCS)")
    doc_hash: Optional[str] = Field(
        default=None,
        description="sha256 do PDF congelado no /start; conferido contra os bytes baixados",
    )
    force: bool = Field(default=False, description="Reservado: ignora cache quando houver cache")
    provider: Optional[str] = Field(default=None, description="Override do provider LLM")
    model: Optional[str] = Field(default=None, description="Override do modelo de OCR")


class IndexarResponse(BaseModel):
    """`{success, documento_indexado, custo, paginas_ocr, …}`.

    `paginas_ocr` é a lista das FOLHAS lidas por OCR, não a contagem: a
    contagem responde "quanto custou" e a lista responde "quais citações são
    contra o texto OCR e não contra o PDF" — que é a pergunta que o humano faz
    quando confere a evidência (§7-risco-6).
    """

    success: bool
    documento_indexado: Optional[dict[str, Any]] = None
    metodo: Optional[str] = None
    gate_ocr: dict[str, Any] = Field(default_factory=dict)
    paginas_ocr: list[int] = Field(default_factory=list)
    cache_hit: bool = False
    custo: float = 0.0
    cost_usd: float = 0.0
    model: Optional[str] = None
    error: Optional[str] = None


__all__ = ["IndexarRequest", "IndexarResponse"]

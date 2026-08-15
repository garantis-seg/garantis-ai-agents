"""Endpoint do INDEXADOR de documento — a camada P do Agente Investigador.

`POST /doc-indexer/indexar` recebe `{doc_id, gcs_path | pdf_base64, doc_hash?}`
e devolve o `DocumentoIndexado` serializado, que o
`garantis_shared.calculo_fichas.documento.DocumentoIndexado.from_dict`
desserializa do outro lado sem perda (contrato provado em teste, §9.3).

Este endpoint **não é um agente**: é código determinístico com exatamente uma
chamada de OCR, e só quando o gate por página acusa. O timeout de referência do
desenho (§8.3) é 900s — um PDF de 300 páginas com OCR — e não vive aqui: o
cliente o impõe (`TIMEOUT_INDEXADOR_S=900` em `garantis_shared.fichas.c4_agentes`)
e o Cloud Run é o TETO, em `cloudbuild-deploy.yaml` (`--timeout`).

Os dois têm de andar juntos, e até 2026-08-14 não andavam: o Cloud Run estava em
300s contra 600s do calculador e 900s do indexador, ou seja, o servidor cortava a
request antes de qualquer cliente desistir — 504 com o custo do LLM já pago. O
`--timeout` do deploy subiu para 900s; quem mexer em um dos dois números tem de
mexer no outro, e o do Cloud Run nunca pode ficar ABAIXO do maior timeout de
cliente.

Contrato de envelope como o resto do repo: `{success, …, model, cost_usd}`, e
falha de leitura devolve `success=false` com **HTTP 200** — quem decide o que
fazer com um documento ilegível é o step S2b, não o servidor. 500 fica só para
falha inesperada de infraestrutura.
"""

import logging

from fastapi import APIRouter, HTTPException

from ...agents.doc_indexer import indexar
from ...agents.doc_indexer.schemas import IndexarRequest, IndexarResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/doc-indexer", tags=["doc-indexer"])


@router.post("/indexar", response_model=IndexarResponse)
async def indexar_endpoint(request: IndexarRequest):
    """Indexa um PDF: texto nativo (PyMuPDF) → gate por página → OCR do que faltou.

    Atrás da flag `FICHAS_DOC_INDEXER_ENABLED`. Com ela OFF a rota responde
    `success=false, error="doc_indexer_desligado"` sem tocar em GCS nem em
    modelo — ship inerte, flip explícito.

    Response: `{success, documento_indexado, metodo, gate_ocr, paginas_ocr,
    cache_hit, custo, cost_usd, model, error?}`.
    """
    try:
        return await indexar(
            request=request, provider=request.provider, model=request.model,
        )
    except Exception as e:
        logger.error(f"doc_indexer indexar failed: {repr(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=repr(e))

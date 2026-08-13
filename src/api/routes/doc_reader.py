"""Endpoints do LEITOR — a camada L do Agente Investigador (§2, §8.3).

    POST /doc-reader/perguntar   pergunta pontual  → resposta ≤400 tok + [sid]
    POST /doc-reader/resumir     missão ampla      → resumo ≤2000 tok + [sid]

Os dois recebem o `DocumentoIndexado` que o `/doc-indexer/indexar` produziu e
**só ele**: o Leitor não vê o grafo, não vê os outros documentos, não vê a
rodada. Essa cegueira é o produto (§2) — é o que impede o *telephone game* que a
pesquisa §4.1 nomeia como anti-padrão, e o que faz a resposta ser sobre o que o
documento diz em vez de sobre o que o cálculo espera ouvir.

O timeout de referência do desenho (§8.3) é 300s para os dois, e vive na
configuração do Cloud Run, não aqui.

Contrato de envelope como o resto do repo: `{success, …, model, cost_usd}`, e
falha de leitura ou de validação devolve `success=false` com **HTTP 200** — quem
decide o que fazer com um envelope reprovado é o Investigador, que o transforma
em rejeição de rodada e itera com contexto. 500 fica só para falha inesperada de
infraestrutura.

⚑ `encontrou=false` **não é erro**: é `success=true` com a lacuna nomeada, a
resposta legítima e barata que o §2.2 exige. Um documento que comprovadamente
não tem o dado é informação útil, e devolvê-la como falha faria o Investigador
insistir onde não há nada.
"""

import logging

from fastapi import APIRouter, HTTPException

from ...agents.doc_reader import perguntar, resumir
from ...agents.doc_reader.schemas import (
    PerguntarRequest,
    PerguntarResponse,
    ResumirRequest,
    ResumirResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/doc-reader", tags=["doc-reader"])


@router.post("/perguntar", response_model=PerguntarResponse)
async def perguntar_endpoint(request: PerguntarRequest):
    """Pergunta pontual sobre UM documento indexado. Toda afirmação carrega `[sid]`.

    O `doc_hash` do request é conferido contra o do documento; divergência é
    `error="documento_mudou"` — nunca se lê outro documento em silêncio (§1.6).

    Response: `{success, resposta, citacoes, confianca, objeto_da_confianca,
    encontrou, lacuna, cache_hit, self_consistency_n, model, cost_usd, error?}`.
    """
    try:
        return await perguntar(
            request=request, provider=request.provider, model=request.model,
        )
    except Exception as e:
        logger.error(f"doc_reader perguntar failed: {repr(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=repr(e))


@router.post("/resumir", response_model=ResumirResponse)
async def resumir_endpoint(request: ResumirRequest):
    """Missão ampla sobre UM documento indexado — a PRIMEIRA passada num colossal.

    O Investigador chama esta antes de perguntar, para saber o que perguntar
    (§2.2). A `pagina` de cada evidência é resolvida pelo CÓDIGO a partir do
    `sid`, nunca pelo modelo (§6.2).

    Response: `{success, resumo, evidencias, confianca, objeto_da_confianca,
    cobertura, lacunas, cache_hit, self_consistency_n, model, cost_usd, error?}`.
    """
    try:
        return await resumir(
            request=request, provider=request.provider, model=request.model,
        )
    except Exception as e:
        logger.error(f"doc_reader resumir failed: {repr(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=repr(e))

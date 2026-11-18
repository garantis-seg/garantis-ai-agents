"""A porta de entrada e saída do núcleo `garantis_shared.leitura`.

    POST /leitura/executar

O núcleo (perguntar, conferir, decidir, registrar) é puro e mora no shared. Ele não fala
com o modelo: quem o chama injeta a função `chamar`. No worker, essa função é um POST
para esta rota. Esta rota não sabe nada de ficha, de timeline nem de regra de negócio:
recebe o pedido pronto e o schema, chama o modelo e devolve a resposta crua com o uso.
A pergunta (política) fica no shared, e por isso muda sem deploy deste serviço.

Decisão do Alfredo em 17/11/2026 (CADERNO do shared, item 74).

Códigos: 200 sempre que o modelo respondeu, mesmo com JSON inválido (`resposta` nula e
`erro` com o motivo: a decisão é de quem chama). 500 na falha de infraestrutura.
"""
import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from garantis_shared.llm_models import MODELS

from ...providers import create_provider
from ...utils.llm_json import parse_llm_json

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/leitura", tags=["leitura"])


class Parametros(BaseModel):
    model_config = ConfigDict(extra="forbid")
    #: `None` = o padrão do modelo.
    temp: Optional[float] = 0.0
    #: Orçamento de raciocínio. `None` = não manda (o argon recusa `thinking_config`).
    pensar: Optional[int] = None
    max_tokens: int = Field(default=16384, ge=256, le=65535)


class ExecutarRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pedido: str = Field(min_length=1)
    # `schema_` com alias: `schema` é nome reservado do BaseModel.
    schema_: dict[str, Any] = Field(alias="schema")
    modelo: str
    params: Parametros = Field(default_factory=Parametros)
    #: Quem pede, para o log e o custo (ex.: "timeline_carf_v2").
    pergunta: str = ""


class Uso(BaseModel):
    entrada: int = 0
    saida: int = 0
    custo_usd: float = 0.0
    modelo: str = ""


class ExecutarResponse(BaseModel):
    resposta: Any = None
    texto: str = ""
    uso: Uso
    erro: Optional[str] = None


@router.post("/executar", response_model=ExecutarResponse)
async def executar(req: ExecutarRequest) -> ExecutarResponse:
    if req.modelo not in MODELS:
        raise HTTPException(status_code=422, detail=f"modelo fora do catálogo: {req.modelo}")
    extra: dict[str, Any] = {}
    if req.params.pensar is not None:
        extra["thinking_budget"] = req.params.pensar
    try:
        r = await create_provider("gemini").agenerate(
            req.pedido, model=req.modelo, temperature=req.params.temp,
            max_tokens=req.params.max_tokens, response_schema=req.schema_, **extra)
    except Exception as e:
        logger.error("leitura/executar falhou pergunta=%s modelo=%s: %r", req.pergunta, req.modelo, e,
                     exc_info=True)
        raise HTTPException(status_code=500, detail=repr(e)[:500])
    uso = Uso(entrada=r.input_tokens, saida=r.output_tokens, modelo=r.model,
              custo_usd=float((getattr(r, "metadata", None) or {}).get("cost_usd", 0.0) or 0.0))
    try:
        resposta, erro = parse_llm_json(r.text), None
    except Exception as e:  # noqa: BLE001 — quem chama decide o que fazer com o texto ruim
        resposta, erro = None, f"json_invalido: {type(e).__name__}: {str(e)[:200]}"
    logger.info("leitura/executar pergunta=%s modelo=%s entrada=%s saida=%s erro=%s",
                req.pergunta, req.modelo, uso.entrada, uso.saida, erro)
    return ExecutarResponse(resposta=resposta, texto=r.text or "", uso=uso, erro=erro)

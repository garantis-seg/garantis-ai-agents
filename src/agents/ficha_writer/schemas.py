"""Pydantic schemas pro ficha_writer agent (FichaJSON v2 — slots de texto).

Contrato de wire FIXO (alinhado com o caller frontend-api, shape ACHATADO):
cada slot e uma STRING individual ("bullets[0]".."bullets[3]", "merito.p1",
"merito.p2", "valor.descricao", ...), com limite em `max` e `path` informativo.
Nao existem tipos compostos — a response e um objeto plano nome -> string.

Retry cirurgico por slot: quando `campos_com_erro` esta presente, o agent gera/
corrige SO os campos listados la (a request ainda traz os specs desses campos
em `campos`) e a response traz SO eles.
"""

from typing import Any, Optional

from pydantic import BaseModel, Field


class CampoSpec(BaseModel):
    """Spec de UM slot de texto (sempre string simples).

    `max` e uma restricao DURA de caracteres — o layout do PDF quebra se
    estourar. O prompt inclui o limite; a validacao dura fica com o caller
    (aqui so reportamos presenca + tipo string).
    """

    nome: str = Field(description="Chave do slot na response (ex.: 'bullets[2]', 'merito.p1').")
    path: str = Field(
        default="",
        description="Path informativo do slot na FichaJSON (ex.: 'merito.p1').",
    )
    max: int = Field(description="Limite DURO de caracteres do slot.")
    guidance: str = Field(
        default="",
        description="Instrucao especifica de conteudo/tom p/ este slot.",
    )
    exemplos: list[str] = Field(
        default_factory=list,
        description="Exemplos de bom preenchimento (few-shot p/ o slot).",
    )

    model_config = {"extra": "ignore"}


class CampoComErro(BaseModel):
    """Um slot que falhou na validacao do caller — entra no retry.

    Quando presente na request, o agent gera/corrige SO os slots listados aqui
    (specs correspondentes seguem em `campos`) e a response traz SO eles.
    """

    nome: str = Field(description="Nome do slot com erro (deve casar com uma CampoSpec).")
    erro: str = Field(description="Descricao do erro (ex.: 'bullets[2] > 150 chars').")
    valor_anterior: Any = Field(
        default=None,
        description="Valor (string) que o slot tinha e falhou.",
    )

    model_config = {"extra": "ignore"}


class FichaWriteFieldsRequest(BaseModel):
    """Request do POST /ficha/write-fields."""

    dossie: dict[str, Any] = Field(
        description=(
            "Dict livre com os fatos: consolidado textual + dados determinísticos "
            "(processo, decisões com datas, valores com origem, CDAs, andamentos "
            "recentes, temperatura já calculada)."
        ),
    )
    campos: list[CampoSpec] = Field(
        description="Specs dos slots de texto (strings individuais).",
    )
    campos_com_erro: Optional[list[CampoComErro]] = Field(
        default=None,
        description=(
            "Opcional (retry): quando presente, gerar/corrigir SO estes slots "
            "e responder SO com eles."
        ),
    )
    provider: Optional[str] = Field(default=None, description="LLM provider override.")
    model: Optional[str] = Field(default=None, description="Model override.")

    model_config = {"extra": "ignore"}


class FichaWriteFieldsResponse(BaseModel):
    """Response do POST /ficha/write-fields.

    `campos` traz exatamente os nomes pedidos — TODOS strings simples. No retry
    (campos_com_erro presente na request) traz SO os slots corrigidos. Em falha
    (parse/campo faltando/nao-string), success=false + error claro e
    `campos` = {} — o caller decide o retry.
    """

    success: bool
    campos: dict[str, str] = Field(default_factory=dict)
    model: str = ""
    cost_usd: float = 0.0
    error: Optional[str] = None

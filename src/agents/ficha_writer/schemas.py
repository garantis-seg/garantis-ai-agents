"""Pydantic schemas pro ficha_writer agent (FichaJSON v2 — slots de texto).

Contrato de wire FIXO: o caller (frontend-api) ja esta sendo implementado contra
estes shapes. Nao mudar nomes de campo sem alinhar com o caller.

O request carrega os FATOS (dossie) + as SPECS dos campos a escrever. A response
devolve exatamente os campos pedidos (por nome), cada um no tipo declarado na spec:
- tipo="string"        -> str
- tipo="array_string"  -> list[str]  (quantidade itens)
- tipo="objeto_p1_p2"  -> {"p1": str, "p2": str}
"""

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


TipoCampo = Literal["string", "array_string", "objeto_p1_p2"]


class CampoSpec(BaseModel):
    """Spec de UM slot de texto a escrever.

    limite_chars e uma restricao DURA — o layout do PDF quebra se estourar. O
    prompt inclui o limite; a validacao dura fica com o caller (aqui so reportamos).
    """

    nome: str = Field(description="Chave do campo na ficha (identidade do slot).")
    tipo: TipoCampo = Field(description="Forma do valor: string, array_string ou objeto_p1_p2.")
    limite_chars: int = Field(
        description=(
            "Limite DURO de caracteres. Em array_string/objeto_p1_p2 aplica-se a "
            "CADA item/parte."
        ),
    )
    quantidade: Optional[int] = Field(
        default=None,
        description="So p/ tipo=array_string: quantos itens produzir.",
    )
    guidance: str = Field(
        default="",
        description="Instrucao especifica de conteudo/tom p/ este campo.",
    )
    exemplos: list[str] = Field(
        default_factory=list,
        description="Exemplos de bom preenchimento (few-shot p/ o campo).",
    )


class CampoComErro(BaseModel):
    """Um campo que falhou na validacao do caller — entra no retry.

    Quando presente na request, o prompt inclui o erro e instrui correcao
    CIRURGICA so destes campos (os demais nao devem ser reescritos).
    """

    nome: str = Field(description="Nome do campo com erro (deve casar com uma CampoSpec).")
    erro: str = Field(description="Descricao do erro (ex.: 'estourou limite: 142/120 chars').")
    valor_anterior: Any = Field(
        default=None,
        description="Valor que o campo tinha e falhou (str | list | dict, conforme o tipo).",
    )


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
        description="Specs dos slots de texto a escrever.",
    )
    campos_com_erro: Optional[list[CampoComErro]] = Field(
        default=None,
        description=(
            "Opcional (retry): quando presente, corrigir CIRURGICAMENTE so estes "
            "campos, ecoando o erro no prompt."
        ),
    )
    provider: Optional[str] = Field(default=None, description="LLM provider override.")
    model: Optional[str] = Field(default=None, description="Model override.")

    model_config = {"extra": "ignore"}


class FichaWriteFieldsResponse(BaseModel):
    """Response do POST /ficha/write-fields.

    `campos` traz exatamente os nomes pedidos (na request), cada um no tipo
    declarado. Em falha (parse/tipo/campo faltando), success=false + error claro
    e `campos` = {} — o caller decide o retry.
    """

    success: bool
    campos: dict[str, Any] = Field(default_factory=dict)
    model: str = ""
    cost_usd: float = 0.0
    error: Optional[str] = None

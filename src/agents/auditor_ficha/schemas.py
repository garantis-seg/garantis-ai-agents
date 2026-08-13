"""Schemas do AUDITOR DE FICHA (S6).

O contrato de SAIDA nao e escolha deste repo: ele esta cravado no docstring de
`garantis_shared.fichas.runner.auditar` e o ramo de reprovacao do workflow
(`fichas/dbos_workflow.py`, S6) JA le `aprovado` e `reprovacoes`. Qualquer
divergencia de forma aqui quebra o pipeline no dia em que ligarem
`AUDITOR_ENABLED`:

    {"aprovado": bool,
     "auditor_enabled": True,
     "modelo": str,
     "reprovacoes": [{"campo": str, "motivo": str, "regra": str}],
     "cost_usd": float}

**Reprovacao TIPADA, nunca nota/score** (PESQUISA-AGENTE-INVESTIGADOR-2026-08
§4). Um score obriga o consumidor a escolher um corte arbitrario e nao diz o
que corrigir; a tripla (campo, motivo, regra) diz onde, por que e com que
autoridade. `campo` fala o MESMO idioma do `campos_com_erro` do harness (slots
achatados: "merito.p1", "bullets[0]", "ultima_decisao.texto"), porque a
reprovacao volta ao S4 como retry cirurgico por campo.
"""

from typing import Any, Optional

from pydantic import BaseModel, Field


class Reprovacao(BaseModel):
    """UMA reprovacao — o campo, o porque e a ancora no Livro.

    Sem ancora nao ha reprovacao: `regra` e o que separa "o auditor achou feio"
    de "o Livro proibe". E tambem o que torna o falso-positivo auditavel — da
    pra ir na regra citada e discordar dela.
    """

    campo: str = Field(
        description=(
            "Slot achatado da ficha, no idioma do `campos_com_erro` do harness "
            "(ex.: 'merito.p1', 'bullets[0]', 'ultima_decisao.texto'). E por ele "
            "que o S4 faz o retry cirurgico."
        )
    )
    motivo: str = Field(
        description=(
            "UMA frase: o que esta errado e, quando cabe, o que o dossie diz no "
            "lugar. Volta ao redator como instrucao de correcao."
        )
    )
    regra: str = Field(
        description=(
            "ID da regra do Livro que sustenta a reprovacao (ex.: 'S7', 'S40', "
            "'E14/S13', 'S15'). Reprovacao sem ancora e opiniao."
        )
    )

    model_config = {"extra": "ignore"}


class AuditarFichaRequest(BaseModel):
    """Request do POST /ficha/auditar.

    `ficha_json` e `dossie` sao AMBOS dado de terceiro (o primeiro saiu de um
    LLM, o segundo de tribunal/provider) — os dois entram no prompt cercados
    por fence com boundary aleatorio. Ver prompts.py.
    """

    ficha_json: dict[str, Any] = Field(
        description="A ficha redigida pelo S4, ja aprovada no S5 (deterministico)."
    )
    dossie: dict[str, Any] = Field(
        default_factory=dict,
        description="Os FATOS congelados: a unica fonte contra a qual a prosa e conferida.",
    )
    tipo: Optional[str] = Field(
        default=None,
        description=(
            "Tipo da oportunidade (nova_apolice / substituicao_fianca / ...). "
            "Muda quais proibicoes do Livro se aplicam por slot."
        ),
    )
    provider: Optional[str] = None
    model: Optional[str] = Field(
        default=None,
        description=(
            "Modelo do auditor. Precisa ser DIFERENTE do redator (S4): quem "
            "confere nao pode ser quem escreveu — os erros se confirmariam."
        ),
    )

    model_config = {"extra": "ignore"}


class AuditarFichaResponse(BaseModel):
    """Response do POST /ficha/auditar — envelope da casa + contrato do runner.

    O envelope da casa ({success, ..., model, cost_usd}) e o contrato do
    `runner.auditar` ({aprovado, auditor_enabled, modelo, reprovacoes,
    cost_usd}) convivem no MESMO objeto de proposito: o cliente HTTP do shared
    repassa os campos do contrato sem remontar nada, e `success` continua
    dizendo se a CHAMADA funcionou — que e pergunta diferente de `aprovado`
    (se a FICHA passou).

    ⚠️ Falha de chamada (`success=false`) NAO e aprovacao. Nesse caso
    `aprovado` vem False e `auditor_enabled` False: o caller ve que nenhuma
    auditoria aconteceu e trata como o stub trataria — nunca como ficha
    auditada e limpa.
    """

    success: bool
    aprovado: bool = False
    auditor_enabled: bool = False
    modelo: Optional[str] = None
    reprovacoes: list[dict[str, Any]] = Field(default_factory=list)
    pendencias: list[str] = Field(default_factory=list)
    #: Espelho de `modelo` no idioma do envelope da casa ({success, model,
    #: cost_usd}), pra rota do ai-agents parecer com todas as outras.
    model: str = ""
    cost_usd: float = 0.0
    error: Optional[str] = None


__all__ = [
    "AuditarFichaRequest",
    "AuditarFichaResponse",
    "Reprovacao",
]

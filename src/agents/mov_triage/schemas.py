"""Pydantic schemas pro mov_triage agent (L1 v7 — triagem 2-estagios, 1o estagio).

TRIAGEM BARATA: uma 1a chamada de baixo custo (prompt curto, gemini-2.5-flash-lite)
que responde os campos baratos + 2 PORTOES de roteamento. Se ambos os portoes =
false, o CODIGO deriva o card enxuto SEM 2a chamada LLM. Se algum portao = true,
o caller roda o passe COMPLETO (/mov-factsheet/classify).

REGRA DE OURO: a triagem so erra pro lado SEGURO (na duvida -> completo).

Reusa os tipos de input do mov_factsheet (ProcessoContext, MovInput, DocAnexado,
FallbackContext) — mesma forma de request, prompt/schema diferentes.

Spec: memory l1-triagem-2estagios + POC /Users/.../prompt_monit_reader/l1_triagem.py
"""

from typing import Any, Optional
from pydantic import BaseModel, Field

# Reusa os tipos de input do mov_factsheet — a triagem espelha o mesmo request.
from ..mov_factsheet.schemas import (
    DocAnexado,
    FallbackContext,
    MovInput,
    ProcessoContext,
)

__all__ = [
    "DocAnexado",
    "FallbackContext",
    "MovInput",
    "ProcessoContext",
    "MovTriageCard",
    "TriageRequest",
    "TriageResponse",
]


# ── Output card da triagem (subconjunto barato + 2 portoes) ───────────────────


class MovTriageCard(BaseModel):
    """Card do 1o estagio. 6 campos baratos.

    Note que `tem_decisao` (campo do card) e SEPARADO de `mov_merito` (portao P1):
    P1 e MAIS LARGO. Uma peticao inicial tem tem_decisao=false MAS mov_merito=true.
    """

    resumo_ato: str = Field(
        description=(
            "~40 palavras EM PORTUGUES CORRETO E ACENTUADO (vai pro usuario final — "
            "use acentos e cedilha: 'decisão', 'execução', 'não'): o que aconteceu "
            "nesta unidade."
        ),
    )
    tipo_doc: str = Field(
        description="Tipo da peca — UM dos valores da taxonomia v1 ensinada no prompt.",
    )
    # ── PORTAO 1 ──
    mov_merito: bool = Field(
        default=False,
        description=(
            "true se este ato DECIDE algo OU traz tese/pedido/prova/desfecho que pode "
            "mover o rumo do processo. Inclui (mesmo SEM julgamento): peticao inicial, "
            "recurso, embargos, excecao de pre-executividade, contestacao, manifestacao "
            "sobre laudo/prova, laudo pericial, certidao de transito em julgado, pedido "
            "de cumprimento de sentenca. false APENAS para ato puramente administrativo/"
            "expediente que NAO carrega tese nem desfecho (juntada, procuracao, guia "
            "paga, comprovante, certidao de publicacao, intimacao de mero expediente)."
        ),
    )
    # ── campo do card (mais restrito que o portao): houve JULGAMENTO? ──
    tem_decisao: bool = Field(
        default=False,
        description=(
            "true SO se houve um pronunciamento que JULGA/DECIDE (sentenca, acordao, "
            "liminar, decisao interlocutoria, despacho decisorio). Uma peticao/recurso "
            "da PARTE NAO e decisao (tem_decisao=false), embora mov_merito=true."
        ),
    )
    # ── PORTAO 2 ──
    mov_garantia_exec: bool = Field(
        default=False,
        description=(
            "REGRA DURA (nosso ativo — nunca deixe passar). true SEMPRE que o ato "
            "MENCIONA qualquer um: seguro garantia/seguro-garantia, APOLICE, FIANCA "
            "bancaria, DEPOSITO (judicial/recursal/em garantia), CAUCAO, garantia "
            "(oferecida/aceita/recusada/substituida/reforcada/levantada/executada), ou "
            "ACIONAMENTO (ordem pra a seguradora/garantidora pagar/depositar o valor "
            "segurado / converter o seguro em pagamento) — MESMO em linguagem "
            "administrativa ('intime-se a garantidora', 'expeca-se mandado a seguradora', "
            "'converta-se o seguro garantia em pagamento', 'execute-se a garantia'); OU "
            "(b) AVANCA a cobranca/execucao CONTRA O TOMADOR (inicio de execucao, "
            "cumprimento de sentenca contra ele, intimacao pra pagar, penhora/bloqueio "
            "de bens dele). NA DUVIDA: true (perder ato de garantia e o pior erro; "
            "mandar a mais custa pouco)."
        ),
    )
    confianca: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Confianca do LLM nesta triagem (0-1).",
    )


# ── Request / Response ────────────────────────────────────────────────────────


class TriageRequest(BaseModel):
    """Espelha MovFactSheetRequest — mesma forma de input, estagio diferente."""

    processo: ProcessoContext
    mov: MovInput
    documentos_anexados: list[DocAnexado] = Field(
        default_factory=list,
        description="Docs vinculados a esta mov via document_movement_links. Vazio = sem doc.",
    )
    fallback_context: Optional[FallbackContext] = Field(
        default=None,
        description="Contexto auxiliar; passar SOMENTE quando documentos_anexados=[]",
    )
    model: Optional[str] = None
    provider: Optional[str] = None


class TriageResponse(BaseModel):
    card: MovTriageCard
    raw_response: Optional[str] = None
    llm_raw_prompt: Optional[str] = None
    prompt_version: Optional[str] = None
    usage: Optional[dict[str, Any]] = None

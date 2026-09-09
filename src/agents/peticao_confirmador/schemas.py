"""Contratos do confirmador comparativo da peticao inicial (C5).

Duas coisas moram aqui, e elas sao DIFERENTES de proposito:

  1. `CONFIRMADOR_RESPONSE_SCHEMA` -- o `response_schema` que vai pro provider.
     ⛔ VERBATIM do arnes de medicao (`d2_prompt.py::SCHEMA`), e e um **dict**, nao
     um modelo Pydantic: o schema que o modelo ve faz parte do que foi medido, e o
     JSON Schema que o Pydantic gera nao e o mesmo (ordem, `title`, `anyOf`). ⭐ E
     structured output do provider -- ⛔ NUNCA parse de prosa.
  2. Os modelos Pydantic do REQUEST/RESPONSE HTTP -- o contrato com o
     `garantis_shared`, validado pelo FastAPI.

⛔ `escolhido` e o INDICE do candidato (0..N), NUNCA o id do documento: o id e um
inteiro longo que um modelo pequeno copia errado e cuja validade so se checa contra
o banco, enquanto 0..N e validavel na hora, contra o proprio conjunto enviado.

⭐ **A VALIDACAO DO VEREDITO NAO MORA AQUI, e isso e deliberado.** O
`garantis_shared` ja tem `_valida_veredito` (`escolhido` nao-inteiro, `bool`, fora
de faixa, `continuacao` invalida -> tudo vira ABSTENCAO). Duplicar aqui criaria dois
donos pra mesma regra, que divergem em silencio. A responsabilidade desta rota e
devolver o que o modelo disse, no formato do contrato.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field, StrictInt

__all__ = [
    "CONFIRMADOR_RESPONSE_SCHEMA",
    "CandidatoConfirmador",
    "ConfirmadorCard",
    "ConfirmadorRequest",
    "ConfirmadorResponse",
    "ProcessoConfirmador",
]


# ⛔ VERBATIM do arnes de medicao (`d2_prompt.py::SCHEMA`). NAO EDITE.
CONFIRMADOR_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "escolhido": {
            "type": "integer",
            "description": ("NUMERO do candidato que e a peca inaugural deste processo. "
                            "0 = NENHUM dos candidatos e a peca inaugural."),
        },
        "continuacao": {
            "type": "array",
            "items": {"type": "integer"},
            "description": ("NUMEROS dos candidatos que sao a CONTINUACAO da mesma peca, "
                            "na ordem de leitura. Vazia se a peca cabe num documento so."),
        },
        "motivo": {"type": "string", "description": "Uma frase curta."},
    },
    "required": ["escolhido", "continuacao", "motivo"],
}


# ── Request ───────────────────────────────────────────────────────────────────


class ProcessoConfirmador(BaseModel):
    """Contexto do processo como o `garantis_shared` o manda.

    ⛔ **Nem todo campo daqui entra no prompt.** So os 6 de
    `prompts.CAMPOS_DO_PROCESSO_NO_PROMPT` -- `classe_cnj_code`, `materia`,
    `nm_tomador` e `cnpj_tomador` chegam porque vem do mesmo loader do L1-mov e
    ficam FORA da chamada: numero medido so descreve o payload medido.
    """

    cnj: Optional[str] = None
    classe: Optional[str] = None
    classe_cnj_code: Optional[int] = None
    tribunal: Optional[str] = None
    assunto: Optional[str] = None
    polo_ativo: Optional[str] = None
    polo_passivo: Optional[str] = None
    materia: Optional[str] = None
    nm_tomador: Optional[str] = None
    cnpj_tomador: Optional[str] = None


class CandidatoConfirmador(BaseModel):
    """Um candidato do pool. `n` e informativo; quem numera e a POSICAO na lista."""

    n: Optional[int] = None
    doc_key: Optional[str] = Field(
        default=None,
        description=("Identidade OPACA do documento, pro log deste agent. ⛔ NAO vai "
                     "pro prompt -- nao ajuda a ler e daria pista de proveniencia."),
    )
    titulo: Optional[str] = None
    head: Optional[str] = Field(
        default=None,
        description="INICIO do texto, ja truncado em `head_chars` pelo caller.",
    )


class ConfirmadorRequest(BaseModel):
    processo: ProcessoConfirmador = Field(default_factory=ProcessoConfirmador)
    head_chars: int = Field(
        default=3000,
        gt=0,
        description=("A JANELA, DECLARADA PELO CALLER. ⛔ Ela e a defesa estrutural "
                     "contra copia-integral e o dono dela e o `garantis_shared` "
                     "(`_CONFIRMADOR_HEAD_CHARS`), onde o guard a alcanca."),
    )
    #: ⛔⛔ **`min_length=1`: pool VAZIO nao e uma pergunta, e nao se paga por ele.**
    #: Ate 2026-09-09 este campo era `default_factory=list`, entao `POST {}` montava um
    #: request valido com ZERO candidatos, o agente chamava `agenerate` sem
    #: curto-circuito, e a rota devolvia **200 pagando** por um prompt que dizia
    #: *"CANDIDATOS (0 documentos)"* e *"Escolha entre os candidatos [1] a [0]"*.
    #: Achado sondando a rota recem-deployada com `{}` (esperava-se 422; veio 200).
    #: ⭐ O caller de producao nunca manda vazio -- o `garantis_shared` curto-circuita em
    #: `if not candidatos`. Justamente por isso o vazamento seria **invisivel**: so
    #: chegaria aqui por bug de caller, retry malformado ou sonda, e cada um paga calado.
    #: ⭐ A recusa e DECLARATIVA (Pydantic), nao um `if` no agente: um `if` seria um 2o
    #: dono da mesma pre-condicao, e o schema ja e quem responde "este request e uma
    #: pergunta?". Sai 422 -- e 422 chega no caller como abstencao, que e o estado de hoje.
    candidatos: list[CandidatoConfirmador] = Field(min_length=1)
    model: Optional[str] = None
    provider: Optional[str] = None


# ── Response ──────────────────────────────────────────────────────────────────


class ConfirmadorCard(BaseModel):
    """O veredito CRU do modelo, dentro da forma do contrato.

    ⛔ Sem clamp: `escolhido` fora de faixa segue fora de faixa aqui e o
    `_valida_veredito` do `garantis_shared` o transforma em ABSTENCAO. Consertar em
    silencio esconderia um modelo que nao entendeu o contrato.

    🚨🚨 **`strict=True` E LOAD-BEARING, e sem ele esta rota DESARMA a guarda do
    `garantis_shared`.** Aquele lado checa `isinstance(e, bool)` de proposito, porque
    `bool` e subclasse de `int` em Python e um `true` do JSON passaria por indice 1 --
    "o modelo dizendo sim" virando "o primeiro candidato", que e a forma mais
    silenciosa possivel de o frame comparativo virar indutor. ⛔ Mas a coercao LAX do
    Pydantic (medida: `True -> 1`, `"2" -> 2`, `2.0 -> 2`) acontece **antes** de o
    payload sair daqui, e entrega um `1` limpo do outro lado ⇒ a guarda de la fica
    inalcancavel e o defeito passa como afirmacao.
    ⭐ Com `strict`, o valor fora do tipo e REJEITADO, a rota devolve 500, e o caller
    trata como `decidiu=False` ⇒ ABSTENCAO. A direcao do erro fica certa: na duvida
    nao se afirma.
    ⛔ Vale para `continuacao` pelo mesmo motivo -- `[true]` viraria `[1]`.
    """

    escolhido: int = Field(strict=True)
    continuacao: list[StrictInt] = Field(default_factory=list)
    motivo: str = ""


class ConfirmadorResponse(BaseModel):
    card: ConfirmadorCard
    raw_response: Optional[str] = None
    llm_raw_prompt: Optional[str] = None
    prompt_version: Optional[str] = None
    usage: Optional[dict[str, Any]] = None

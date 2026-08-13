"""Schemas do VERIFICADOR CEGO (onda 9) — `verificar_par`, por PAR.

O modo antigo (`auditar_evidencias`) e o modo cego respondem a mesma pergunta
semantica, mas com contextos OPOSTOS:

    auditar_evidencias  ->  grafo inteiro + TODAS as evidencias + textos inteiros
    verificar_par       ->  UMA afirmacao + UMA ancora + UM trecho. Mais nada.

A diferenca nao e economia de token: e a medicao do HALLMARK (DESENHO §2.3 /
pesquisa §4.5) de que **dar contexto e ferramenta ao verificador inflou os
falsos positivos ~5x**. Ver o grafo e ver o historico de construcao; ver o
historico e herdar a hipotese de quem construiu. O verificador cego nao sabe
quem escreveu a afirmacao, nao sabe que celula ela e, nao sabe o que mais o
documento diz. So ve o par.

Duas consequencias de contrato, ambas deliberadas:

1. **Quatro rotulos, nao dois.** `supported | partial | contradicted |
   irrelevant`. Binario colapsa dois donos diferentes no mesmo balde: `partial`
   e fila de REFINAMENTO (a celula existe, a citacao esta curta), `contradicted`
   e BUG DE EXTRACAO (alta prioridade) e `irrelevant` e BUG DE RETRIEVAL (dono
   diferente). Nenhum vendor entrega isso — Google colapsa parcial em
   ungrounded, Azure e binario e ingles-only (pesquisa §6.2).
2. **`motivo_tipado` e ENUM FECHADO**, porque o QA agrega por ele, como ja faz
   com `Rejeicao.codigo`. Os itens vem do docstring do `schemas.py` deste mesmo
   pacote, que ja listava as perguntas certas — em PROSA. Prosa nao agrega em
   metrica.

O verificador **nao tem ferramenta de lookup**. Se precisa de mais contexto que
o trecho, o veredito e `partial` com `motivo_tipado=trecho_incompleto`, e e o
Investigador que decide se amplia a citacao. Quem verifica nao investiga.
"""

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

#: Os quatro rotulos, com o DONO de cada fila (DESENHO §2.3).
VEREDITOS: tuple[str, ...] = ("supported", "partial", "contradicted", "irrelevant")

#: Enum FECHADO de motivo. Fechado porque o QA agrega por ele; texto livre aqui
#: viraria 40 variacoes da mesma causa e nenhuma metrica.
MOTIVOS_TIPADOS: tuple[str, ...] = (
    "numero_diferente",
    "periodo_diferente",
    "tributo_diferente",
    "base_vs_credito",
    "principal_vs_consolidado",
    "trecho_nao_menciona",
    "trecho_incompleto",
    "sujeito_passivo_diferente",
)

#: O unico motivo compativel com `supported` — nao ha o que apontar.
MOTIVO_OK = "sem_divergencia"

Veredito = Literal["supported", "partial", "contradicted", "irrelevant"]


class NumeroDivergente(BaseModel):
    """Um par (numero na afirmacao, numero no trecho) que NAO bate.

    Computado em CODIGO (`_numeros_divergentes`), nunca pelo modelo: alucinacao
    numerica de alta confianca e o risco nº 3 da pesquisa, e pedir ao proprio
    modelo que a detecte e pedir ao raposo que conte as galinhas. O LLM so
    EXPLICA a divergencia que o codigo ja achou.
    """

    na_afirmacao: str
    no_trecho: str

    model_config = {"extra": "ignore"}


class VerificarParRequest(BaseModel):
    """Request do POST /calculo-ficha/verificar-par.

    Note o que NAO existe aqui: `celulas`, `documentos`, `evidencias`,
    `rodadas_anteriores`, `celula_id`. A ausencia e o desenho.
    """

    afirmacao: str = Field(
        description=(
            "UM claim atomico, como 'o IRPJ principal mantido e 723810827.57'. "
            "Nao mande a celula inteira nem o grafo: o verificador julga UMA "
            "afirmacao contra UM trecho."
        )
    )
    trecho: str = Field(
        description=(
            "O texto do sid/pid, buscado pelo CODIGO no DocumentoIndexado. O "
            "modelo nao escolhe o trecho — se escolhesse, escolheria o que "
            "confirma."
        )
    )
    ancora: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "A `Ancora` (documento.py) resolvida pelo codigo, ecoada na resposta "
            "para o chamador casar veredito com posicao. Nao vai para o prompt "
            "como contexto de julgamento — doc_id e hash nao ajudam a julgar "
            "semantica e so dariam pistas de proveniencia ao verificador cego."
        ),
    )
    n_dinco: Optional[int] = Field(
        default=None,
        description=(
            "Override do N do DINCO nesta chamada. Ausente => o do ambiente "
            "(`SELF_CONSISTENCY_N`), e N efetivo 1 quando FICHAS_DINCO_ENABLED "
            "esta desligada. O N EFETIVO vai sempre na resposta."
        ),
    )
    distractors: Optional[list[Any]] = Field(
        default=None,
        description=(
            "Distractors ja prontos (o chamador que tem o documento na mao gera "
            "melhores). Ausente => gerados em codigo por `gerar_distractors` a "
            "partir do proprio trecho."
        ),
    )
    provider: Optional[str] = None
    model: Optional[str] = Field(
        default=None,
        description=(
            "Modelo do verificador. Precisa ser DIFERENTE do calculador: dois "
            "erros correlacionados do mesmo modelo se confirmam mutuamente."
        ),
    )

    model_config = {"extra": "ignore"}


class VerificarParResponse(BaseModel):
    """Response do POST /calculo-ficha/verificar-par.

    Envelope da casa `{success, ..., model, cost_usd}`; falha devolve
    `success=false` com HTTP 200 e o harness decide a rodada.

    `confianca` + `objeto_da_confianca` sao OBRIGATORIOS no caminho feliz
    (§5.3): confianca viaja em CAMPO, nunca em prosa. "85% de que li o numero
    certo" != "85% de que este e o numero que a celula pede" — sem o objeto
    declarado o numero e ruido com aparencia de rigor.
    """

    success: bool
    veredito: Optional[Veredito] = None
    motivo_tipado: Optional[str] = None
    motivo: str = ""
    numeros_divergentes: list[dict[str, Any]] = Field(default_factory=list)
    confianca: Optional[float] = None
    objeto_da_confianca: Optional[str] = None
    #: TODOS os votos do DINCO (a alegacao + cada distractor). Sem eles
    #: gravados nao ha recalibracao nem investigacao de celula que saiu errada.
    votos: list[dict[str, Any]] = Field(default_factory=list)
    #: O N EFETIVO desta run — `1 + len(distractors)` de verdade usados, nao o
    #: teto pedido. Declarado inclusive com o DINCO OFF (vale 1). O pedido e um
    #: TETO: um trecho pobre em numeros rende menos distractors plausiveis, e
    #: gravar o teto faria a recalibracao comparar DINCO@4 com DINCO@3 como se
    #: fossem a mesma coisa. Metrica de A/B sem o N efetivo e incomparavel.
    self_consistency_n: int = 1
    dinco_enabled: bool = False
    ancora: dict[str, Any] = Field(default_factory=dict)
    model: str = ""
    cost_usd: float = 0.0
    error: Optional[str] = None
    #: Tipo do erro, para o QA agregar: `parse`, `vocabulario`, `envelope`.
    error_tipo: Optional[str] = None


__all__ = [
    "MOTIVOS_TIPADOS",
    "MOTIVO_OK",
    "VEREDITOS",
    "NumeroDivergente",
    "Veredito",
    "VerificarParRequest",
    "VerificarParResponse",
]

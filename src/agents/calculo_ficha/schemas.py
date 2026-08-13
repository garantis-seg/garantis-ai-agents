"""Schemas do agente CALCULADOR (C4) — grafo de celulas com evidencia por dado.

Contrato de wire com o harness (garantis_shared.calculo_fichas). O agente NAO
calcula: ele monta um GRAFO que o codigo resolve. Por isso a response nao tem
campo "valor" — tem celulas, e o numero nasce do motor deterministico do shared.

Duas travas que vivem no schema (nao so no prompt), porque prompt nao e
enforcement:

1. **`dado` nao carrega expressao; `formula` nao carrega valor.** Sao ramos
   disjuntos — um "dado" com expressao seria o LLM calculando escondido.
2. **Taxa nao e celula.** `CelulaDado` rejeita id que se parece com taxa
   (`taxa_*`, `selic_*`, `pct_juros`): juros so entram na fórmula via
   `selic(de, ate)`, resolvido na fonte canonica. Era o furo do V3 — nada
   impedia um `taxa_juros_media` assumido substituir a Selic real.

A validacao ESTRUTURAL definitiva e do shared (gramatica, ciclo, origem
assumida, evidencia verificada, recomputo). Aqui validamos o que da para
validar na fronteira do agente, para devolver erro barato antes de o payload
atravessar a rede.
"""

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

#: Ids que denunciam taxa como celula. O LLM nao imputa taxa: ele chama
#: `selic(de, ate)` na formula e o codigo resolve na serie versionada.
#: Duas listas porque sao dois testes diferentes — misturar as duas numa tupla
#: so exigia filtrar por `endswith("_")` na hora de usar, e o filtro deixava
#: `pct_juros`/`juros_pct`/`fator_selic` como LETRA MORTA (nunca eram testados).
_NOMES_DE_TAXA = ("taxa", "selic")
_PREFIXOS_TAXA_PROIBIDOS = (
    "taxa_", "selic_", "indice_", "pct_juros", "juros_pct", "fator_selic",
)

#: Origens validas — mesmo vocabulario do V3 (o C4 recebe premissas dele como
#: input read-only; traduzir nomes so criaria uma camada a mais para errar).
Origem = Literal["extraida", "factual", "assumida"]


class Evidencia(BaseModel):
    """A citacao EXATA que sustenta um dado. Sem ela o dado nao vira numero.

    `trecho_literal` e copiado do documento, nao parafraseado: o shared confere
    o trecho contra o texto extraido (exato ou similaridade > 0.9) ANTES de
    chamar o auditor. Reescrever de memoria reprova a rodada.
    """

    celula_id: str = Field(description="Id do dado que esta evidencia sustenta.")
    documento: str = Field(description="Identificador do documento citado (nome do arquivo).")
    pagina: int = Field(ge=1, description="Pagina/folha 1-based onde o trecho esta.")
    trecho_literal: str = Field(
        min_length=20,
        description=(
            "Texto COPIADO do documento, com contexto suficiente para ser unico "
            "(minimo 20 chars). Nao parafraseie."
        ),
    )
    localizador: str = Field(
        default="",
        description="Onde na pagina (ex.: 'quadro de exigencias, linha IRPJ').",
    )

    model_config = {"extra": "ignore"}


class CelulaDado(BaseModel):
    """Uma folha do grafo: um valor lido do documento ou derivado de norma.

    `valor` e numero (dinheiro/quantidade/percentual em decimal) OU competencia
    `"YYYY-MM"` (data). Nunca string de dinheiro: "R$ 1.000,00" e texto, nao
    numero, e e assim que valor vira zero silencioso.
    """

    id: str = Field(description="Id minusculo com '_' (ex.: 'irpj_principal').")
    tipo: Literal["dado"] = "dado"
    valor: float | str = Field(description="Numero, ou competencia 'YYYY-MM' para data.")
    origem: Origem = Field(
        description=(
            "'extraida' = copiada do documento (exige evidencia); 'factual' = "
            "decorre de lei/norma (exige nota citando o dispositivo); 'assumida' "
            "= estimativa (PROIBIDA em juros/garantia)."
        )
    )
    confianca: Optional[int] = Field(default=None, ge=0, le=5)
    nota: str = ""
    ressalvas: list[str] = Field(default_factory=list)

    model_config = {"extra": "ignore"}

    @field_validator("id")
    @classmethod
    def _id_nao_pode_ser_taxa(cls, v: str) -> str:
        """Taxa NUNCA e celula do LLM (o furo do V3).

        Um dado chamado `taxa_juros_media` podia substituir `selic()` numa
        formula de juros sem que nada reclamasse. Aqui o id morre no schema.
        """
        low = v.lower()
        if low in _NOMES_DE_TAXA or low.startswith(_PREFIXOS_TAXA_PROIBIDOS):
            raise ValueError(
                f"id {v!r} parece uma taxa. Taxas NAO sao celulas: use "
                "selic(competencia_inicial, competencia_final) na formula — o "
                "codigo resolve na serie oficial versionada"
            )
        return v


class CelulaFormula(BaseModel):
    """Um no interno: uma expressao na gramatica fechada do shared.

    Gramatica: aritmetica (`+ - * / **`), `selic(de, ate)` e `se(cond, sim, nao)`.
    Nada mais parseia — nao ha funcao, atributo, indice, string nem literal
    exotico. O shared roda o parser proprio; nao existe `eval` no caminho.
    """

    id: str = Field(description="Id minusculo com '_' (ex.: 'garantia_total').")
    tipo: Literal["formula"] = "formula"
    expressao: str = Field(
        min_length=1,
        description=(
            "Expressao na gramatica fechada: aritmetica + selic(de, ate) + "
            "se(cond, sim, nao). Referencie celulas pelo id."
        ),
    )
    depende_de: list[str] = Field(
        default_factory=list,
        description="TODOS os ids referenciados na expressao.",
    )
    confianca: Optional[int] = Field(default=None, ge=0, le=5)
    nota: str = ""
    ressalvas: list[str] = Field(default_factory=list)

    model_config = {"extra": "ignore"}


class MontarGrafoRequest(BaseModel):
    """Request do POST /calculo-ficha/montar-grafo (o harness e o caller)."""

    dossie: dict[str, Any] = Field(
        description="Fatos do caso: empresa, processo, decisoes, CDAs, tipo de exigencia."
    )
    documentos: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "documento -> texto, ou documento -> {pagina: texto}. E o material "
            "de onde as evidencias sao copiadas."
        ),
    )
    premissas_v3: Optional[dict[str, Any]] = Field(
        default=None,
        description=(
            "Premissas/calculo do engine V3 (datalake) como INPUT READ-ONLY: "
            "materia-prima a re-verificar com evidencia propria, nunca resposta "
            "a copiar. O V3 tem erro medido de 3x em metade de 414 amostras."
        ),
    )
    indices: dict[str, Any] = Field(
        default_factory=dict,
        description="Metadados da fonte canonica de indices (version, funcao disponivel).",
    )
    rodadas_anteriores: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Historico de rejeicoes (rodada N, o que foi rejeitado, por que). "
            "Quando presente, o prompt exige que cada rejeicao seja endereçada."
        ),
    )
    celula_resultado: str = Field(
        default="garantia_total",
        description="Id EXIGIDO da celula de garantia final.",
    )
    # ── modo INVESTIGADOR (onda 8) — presentes ⇒ tool-use em 2 fases ─────────
    documentos_indexados: Optional[dict[str, Any]] = Field(
        default=None,
        description=(
            "doc_id -> DocumentoIndexado.to_dict() (shared, onda 1). Presente e "
            "nao-vazio ⇒ o agente roda como INVESTIGADOR: decide ferramentas num "
            "turno SEM schema e emite o grafo num turno COM schema (§6). O "
            "Investigador NUNCA recebe texto integral no prompt — so o indice."
        ),
    )
    perguntas_abertas: Optional[list[dict[str, Any]]] = Field(
        default=None,
        description="As celulas rejeitadas da rodada anterior, com endereco (loop onda 6).",
    )
    celulas_congeladas: Optional[list[dict[str, Any]]] = Field(
        default=None,
        description="Celulas aprovadas em rodada anterior — FATO read-only, nao reabrivel.",
    )
    contrato_loop: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None

    model_config = {"extra": "ignore"}


class EvidenciaAncorada(BaseModel):
    """Evidencia da FASE B do investigador (§6.2): ref por ID, zero aninhamento.

    O modelo devolve SO `ancora_sid`/`ancora_pid`; a `Ancora` completa
    (doc_hash, extractor_version, offset, bbox, sha_texto) e preenchida pelo
    CODIGO via `DocumentoIndexado.ancora_de(sid)` — mata a classe inteira
    "o modelo inventou o hash". Os campos compat mantem o fallback fuzzy vivo.
    """

    celula_id: str
    ancora_sid: Optional[str] = Field(
        default=None, description='Id da sentenca citada, ex. "fl5-s12".'
    )
    ancora_pid: Optional[str] = Field(
        default=None, description='Id do paragrafo citado, ex. "fl5-p3".'
    )
    documento: str
    pagina: int = Field(ge=1)
    trecho_literal: str = Field(min_length=20)
    localizador: str = ""
    politica: Literal["span", "paragrafo"] = "span"

    model_config = {"extra": "ignore"}


class GrafoAchatado(BaseModel):
    """Schema de EMISSAO da FASE B (§6.2): profundidade maxima 2, refs por id.

    Lista PLANA de celulas (`depende_de` e lista de ids, nunca objetos
    aninhados) + lista PLANA de evidencias (ref por `celula_id`). Ferramentas
    FSM-based degradam com recursao — e travamos isso por teste
    (`test_schema_profundidade`).
    """

    celulas: list[CelulaDado | CelulaFormula]
    evidencias: list[EvidenciaAncorada] = Field(default_factory=list)
    grau_sugerido: Optional[Literal["exato", "teto", "piso"]] = None
    piso: Optional[float] = None
    teto: Optional[float] = None
    observacao: str = ""

    model_config = {"extra": "ignore"}


class MontarGrafoResponse(BaseModel):
    """Response do POST /calculo-ficha/montar-grafo.

    Mesmo contrato de envelope do write-fields: {success, ..., model, cost_usd}.
    Em qualquer falha devolve success=false + error claro (nunca levanta) — o
    harness transforma isso em rejeicao de rodada e itera.

    NAO existe campo de valor final: o numero e do motor do shared. `piso`/`teto`
    e `grau_sugerido` sao a leitura JURIDICA do agente (o dispositivo cravou o
    saldo mantido? sobrou ambiguidade?), nao aritmetica.
    """

    success: bool
    celulas: list[dict[str, Any]] = Field(default_factory=list)
    evidencias: list[dict[str, Any]] = Field(default_factory=list)
    grau_sugerido: Optional[Literal["exato", "teto", "piso"]] = None
    piso: Optional[float] = None
    teto: Optional[float] = None
    observacao: str = ""
    model: str = ""
    cost_usd: float = 0.0
    error: Optional[str] = None


__all__ = [
    "CelulaDado",
    "CelulaFormula",
    "Evidencia",
    "EvidenciaAncorada",
    "GrafoAchatado",
    "MontarGrafoRequest",
    "MontarGrafoResponse",
    "Origem",
]

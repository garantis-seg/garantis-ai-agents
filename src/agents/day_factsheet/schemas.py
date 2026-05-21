"""Pydantic schemas pro day_factsheet agent (engine v6_meritos camada 1, tier Degradado-Dia).

Output: 1 card por DIA quando o pipeline esta no tier Degradado-Dia
(docs com text_content existem mas sem FK nativa doc-mov). LLM correlaciona
movs+docs do mesmo dia.

Tier-as-regra-de-jogo: nao eh excecao, eh forma natural de tratar dados
de fontes que nao entregam vinculo per-doc (Judit, jusbrasil sem id, etc.).
Spec: memory engine-v6-pipeline-quality-tiers (refinada 2026-05-21).
"""
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

# ── Sub-objetos (alguns reusados conceitualmente do mov_factsheet) ───────


class DecisaoDoDia(BaseModel):
    """Decisao judicial que ocorreu neste dia (se houver)."""

    tem_decisao: bool = False
    sentido: Optional[Literal["favoravel", "desfavoravel", "parcial", "neutro"]] = None
    instancia: Optional[Literal["1g", "2g", "stj", "stf"]] = None
    natureza: Optional[Literal[
        "procedente", "improcedente", "parcialmente_procedente",
        "extinto_sem_merito", "homologatoria", "interlocutoria",
    ]] = None
    transito_certificado: bool = False


class EventoGarantiaDoDia(BaseModel):
    """Evento da garantia neste dia."""

    tipo: Literal[
        "apresentacao", "aceitacao", "recusa", "levantamento",
        "substituicao", "reforço", "nenhum",
    ] = "nenhum"
    motivo: Optional[str] = None


class EventoDoDia(BaseModel):
    """1 evento processual identificado no dia (granularidade abaixo de mov).

    Pode vir tanto de uma mov quanto de um doc — LLM eh quem decide quais
    eventos atomicos extrair. Exemplos:
      - "publicacao da sentenca"
      - "juntada de embargos"
      - "concessao de prazo de 5 dias"
    """

    tipo: Optional[str] = Field(
        default=None,
        description="Categoria do evento (decisao | peticao | anexo | despacho | "
                    "intimacao | publicacao | certidao | outros)",
    )
    descricao: Optional[str] = Field(
        default=None,
        description="1 frase PT-BR descrevendo o evento",
    )
    referencias: list[str] = Field(
        default_factory=list,
        description="mov_ids ou doc_keys que sustentam o evento (audit). "
                    "Se nao da pra correlacionar, lista vazia.",
    )


# ── Output card principal ───────────────────────────────────────────────


class DayFactsheetCard(BaseModel):
    """Sintese de tudo que aconteceu em UM dia de UM processo.

    Cabe em dossier_artifacts.summary com kind='day_factsheet'.
    Entity_id = '{processo_numero}|{date}' pra unicidade.
    """

    processo_numero: str = Field(description="CNJ digits-only (echo do input)")
    date: str = Field(description="YYYY-MM-DD (anchor do card)")

    # Sintese gerada pelo LLM
    resumo_dia: str = Field(
        description="1-3 frases PT-BR descrevendo o que aconteceu no dia",
    )
    eventos: list[EventoDoDia] = Field(
        default_factory=list,
        description="Eventos atomicos identificados (decisao, peticao, etc.)",
    )

    # Decisao + garantia (sub-objetos similares ao mov_factsheet)
    decisao_do_dia: DecisaoDoDia = Field(default_factory=DecisaoDoDia)
    evento_garantia_do_dia: EventoGarantiaDoDia = Field(default_factory=EventoGarantiaDoDia)

    # Relevancia (ajuda L2 a peso/filtrar)
    relevancia_para_merito: Literal["alta", "media", "baixa", "ruido"] = Field(
        default="media",
        description="Quanto este dia influencia o estado do merito",
    )

    # Audit
    docs_considerados: list[str] = Field(
        default_factory=list,
        description="doc_keys que o LLM efetivamente usou na sintese. "
                    "Nao precisa mapear per-evento (lista flat).",
    )
    confianca: float = Field(
        default=0.7,
        ge=0.0, le=1.0,
        description="Confianca do LLM (correlacao multi-mov*multi-doc tende "
                    "a confianca menor que mov-by-mov)",
    )


# ── Request / Response ──────────────────────────────────────────────────


class DayMovInput(BaseModel):
    """Mov que ocorreu neste dia (sem FK doc, por isso entrou no day-grouping)."""

    mov_id: str
    tipo: Optional[str] = None
    texto: str

    model_config = {"extra": "ignore"}


class DayDocInput(BaseModel):
    """Doc juntado neste dia (text_content available, sem FK pra mov)."""

    doc_key: str
    titulo: Optional[str] = None
    tipo: Optional[str] = None
    text_content: str = Field(description="Texto extraido cap'd upstream")

    model_config = {"extra": "ignore"}


class ProcessoContextMin(BaseModel):
    """Contexto minimo do processo (igual ao mov_factsheet)."""

    cnj: str
    classe: Optional[str] = None
    polo_ativo: Optional[str] = None
    polo_passivo: Optional[str] = None

    model_config = {"extra": "ignore"}


class DayFactsheetRequest(BaseModel):
    processo: ProcessoContextMin
    date: str = Field(description="YYYY-MM-DD")
    movs_no_dia: list[DayMovInput] = Field(default_factory=list)
    docs_no_dia: list[DayDocInput] = Field(default_factory=list)
    model: Optional[str] = None
    provider: Optional[str] = None


class DayFactsheetResponse(BaseModel):
    card: DayFactsheetCard
    raw_response: Optional[str] = None
    llm_raw_prompt: Optional[str] = None
    usage: Optional[dict[str, Any]] = None

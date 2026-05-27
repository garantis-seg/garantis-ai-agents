"""Pydantic schemas pro monolith_factsheet agent (engine v6_meritos camada 1, tier monolitico).

Output: 1 card por PROCESSO quando o pipeline esta no tier monolitico
(so PDF monolith em lawsuit_pdfs.pre_extracted_text, sem per-doc nem FK).
Substitui o legacy autos_raw_excerpt direto no L2 — agora autos_raw_excerpt
nem chega no L2; passa pelo monolith_factsheet primeiro pra ser sintetizado.

Tier-as-regra-de-jogo (memory engine-v6-pipeline-quality-tiers): nao eh
excecao, eh forma natural de tratar PDFs blob (upload manual, eproc/PJe
sem per-doc). L2 sempre consome cards estruturados; nao recebe raw.

Spec: memory engine-v6-pipeline-quality-tiers, engine-v6-naming-canonico.
"""
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

# ── Sub-objetos (espelha estrutura de mov_factsheet/day_factsheet) ──────


class DecisaoMonolitica(BaseModel):
    """Decisao judicial vigente identificada no PDF monolitico."""

    tem_decisao: bool = False
    sentido: Optional[Literal["favoravel", "desfavoravel", "parcial", "neutro"]] = None
    instancia: Optional[Literal["1g", "2g", "stj", "stf"]] = None
    natureza: Optional[Literal[
        "procedente", "improcedente", "parcialmente_procedente",
        "extinto_sem_merito", "homologatoria", "interlocutoria",
    ]] = None
    data: Optional[str] = None
    transito_certificado: bool = False
    recorrida: bool = False


class EventoTimelineMonolitica(BaseModel):
    """1 evento identificado na leitura do monolito (cronologico)."""

    data: Optional[str] = None
    tipo: Optional[str] = Field(
        default=None,
        description="decisao | peticao | anexo | despacho | intimacao | publicacao | certidao | outros",
    )
    descricao: Optional[str] = Field(default=None, description="1 frase PT-BR")


class LifecycleGarantiaMonolitica(BaseModel):
    """Evento da garantia/apolice identificado no PDF inteiro."""

    data: Optional[str] = None
    evento: Optional[str] = Field(
        default=None,
        description="apresentacao | aceitacao | recusa | levantamento | substituicao | reforço",
    )
    tipo_garantia: Optional[str] = Field(
        default=None,
        description="seguro_garantia | fianca_bancaria | carta_fianca | deposito_judicial | penhora | fiduciaria",
    )
    motivo_recusa: Optional[str] = None


class PecaPivoMonolith(BaseModel):
    """A peca mais decisiva identificada no PDF monolitico."""

    data: Optional[str] = None
    descricao: Optional[str] = Field(
        default=None,
        description="1 frase explicando porque eh pivo",
    )


# ── Output card principal ───────────────────────────────────────────────


class MonolithFactsheetCard(BaseModel):
    """Sintese de UM processo a partir do PDF monolitico inteiro.

    Cabe em dossier_artifacts.summary com kind='monolith_factsheet'.
    entity_type='processo', entity_id=processo_numero (digits-only).

    Diferente de mov_factsheet (1 card/mov) e day_factsheet (1 card/dia),
    eh 1 card POR PROCESSO inteiro — o blob nao tem estrutura per-event
    confiavel. L2 consome este card como 1 input estruturado.
    """

    processo_numero: str = Field(description="CNJ digits-only (echo do input)")

    resumo_executivo: str = Field(
        description="2-4 frases PT-BR descrevendo o estado atual do processo "
                    "extraido do PDF inteiro (peticao inicial + decisoes recentes)",
    )

    decisao_vigente: DecisaoMonolitica = Field(default_factory=DecisaoMonolitica)

    eventos_principais: list[EventoTimelineMonolitica] = Field(
        default_factory=list,
        description="Top 5-10 eventos identificados no PDF, cronologico ASC",
    )

    lifecycle_garantia: list[LifecycleGarantiaMonolitica] = Field(
        default_factory=list,
        description="Timeline da garantia/apolice extraida do monolito",
    )

    valor_em_disputa: Optional[float] = Field(
        default=None,
        description="Melhor evidencia de valor em disputa (BRL) extraida do PDF",
    )
    valor_garantia: Optional[float] = Field(
        default=None,
        description="Valor da apolice/garantia (BRL)",
    )

    peca_pivo: PecaPivoMonolith = Field(
        default_factory=PecaPivoMonolith,
        description="Peça mais decisiva identificada no PDF",
    )

    proximos_passos_provaveis: list[str] = Field(
        default_factory=list,
        description="2-3 acoes esperadas a partir do estado atual",
    )

    confianca: float = Field(
        default=0.5,
        ge=0.0, le=1.0,
        description="Confianca menor que mov/day_factsheet (0.4-0.7) — leitura "
                    "de PDF inteiro sem mov-by-mov tem ruido inerente",
    )

    pages_used: Optional[int] = Field(
        default=None,
        description="Audit: paginas efetivamente lidas (primeiras N + ultimas M)",
    )


# ── Request / Response ──────────────────────────────────────────────────


class ProcessoContextMin(BaseModel):
    """Contexto minimo do processo."""

    cnj: str
    classe: Optional[str] = None
    polo_ativo: Optional[str] = None
    polo_passivo: Optional[str] = None

    model_config = {"extra": "ignore"}


class MonolithFactsheetRequest(BaseModel):
    processo: ProcessoContextMin
    autos_text: str = Field(
        description="Texto extraido do PDF monolitico (PyMuPDF pre_extracted_text). "
                    "Caller eh responsavel por cap'd (sugestao 60k chars: primeiras 10 pgs + ultimas 50)",
    )
    total_pages: Optional[int] = None
    pages_used: Optional[int] = None
    truncated: bool = False
    model: Optional[str] = None
    provider: Optional[str] = None
    gcs_url: Optional[str] = Field(
        default=None,
        description=(
            "gs://bucket/path do PDF monolitico. Consumido apenas quando "
            "VISION_L1_ENABLED=true — agent lê PDF e passa pro Gemini Vision "
            "em vez de serializar autos_text. Backwards-compatible (None OK)."
        ),
    )


class MonolithFactsheetResponse(BaseModel):
    card: MonolithFactsheetCard
    raw_response: Optional[str] = None
    llm_raw_prompt: Optional[str] = None
    usage: Optional[dict[str, Any]] = None

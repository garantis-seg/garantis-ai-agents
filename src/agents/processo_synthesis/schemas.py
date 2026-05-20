"""Pydantic schemas pro processo_synthesis agent (engine v6_meritos camada 2).

Output cabe em leads.dossier_artifacts com kind='processo_synthesis'.

Spec canonica do plano: c:/Users/Eltonxp/.claude/plans/risk-engine-v6-meritos.md
"""

from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


# ── Sub-objetos ───────────────────────────────────────────────────────────


class DecisaoVigente(BaseModel):
    """Decisao judicial atualmente em vigor neste processo."""

    sentido: Optional[Literal["favoravel", "desfavoravel", "parcial", "neutro"]] = None
    instancia: Optional[Literal["1g", "2g", "stj", "stf"]] = None
    natureza: Optional[Literal[
        "procedente", "improcedente", "parcialmente_procedente",
        "extinto_sem_merito", "homologatoria", "interlocutoria",
    ]] = None
    data: Optional[str] = Field(default=None, description="YYYY-MM-DD da decisao")
    transito_certificado: bool = False
    recorrida: bool = Field(
        default=False,
        description="True se houve recurso interposto contra a decisao vigente",
    )


class LifecycleGarantiaEvent(BaseModel):
    """Evento no ciclo de vida da garantia/apolice neste processo."""

    data: Optional[str] = Field(default=None, description="YYYY-MM-DD")
    mov_id: Optional[str] = None
    evento: Literal[
        "apresentacao", "aceitacao", "recusa", "levantamento", "substituicao", "reforço",
    ]
    tipo_garantia: Optional[Literal[
        "seguro_garantia", "fianca_bancaria", "carta_fianca",
        "deposito_judicial", "penhora", "fiduciaria", "outras",
    ]] = None
    status_pos: Literal[
        "apresentado", "aceito", "recusado", "levantado", "substituido", "nenhum",
    ]
    motivo_recusa: Optional[str] = None


class PecaPivoCandidata(BaseModel):
    """Candidata a peca-pivo dentro deste processo (input pro merito_synthesis decidir)."""

    mov_id: Optional[str] = None
    data: Optional[str] = None
    motivo: Optional[str] = Field(
        default=None,
        description="Por que esta mov define o estado atual do processo",
    )


# ── Output card principal ─────────────────────────────────────────────────


class ProcessoSynthesisCard(BaseModel):
    """Sintese de TODOS os mov_factsheets de UM processo. Camada 2 da engine v6.

    Cabe em dossier_artifacts.summary com kind='processo_synthesis'.
    """

    # Identidade
    processo_numero: str = Field(description="CNJ digits-only ou formatado")
    classe: Optional[str] = None
    classe_cnj_code: Optional[int] = None
    role_no_merito: Optional[Literal["principal", "conexo"]] = Field(
        default=None,
        description="Echo do role declarado no input (do mapeamento merito_membros)",
    )

    # Campo 1: estado processual
    estado_processual: Optional[str] = Field(
        default="",
        description="1-2 frases PT-BR descrevendo o estado atual do processo",
    )

    # Campo 2: decisao vigente
    decisao_vigente: DecisaoVigente = Field(default_factory=DecisaoVigente)

    # Campo 3: lifecycle da garantia
    lifecycle_garantia: list[LifecycleGarantiaEvent] = Field(
        default_factory=list,
        description="Timeline ordenada por data dos eventos de garantia neste processo",
    )

    # Campo 4: risco intermediario do processo
    risco_processo_intermediario: Optional[Literal["Baixo", "Medio", "Alto", "Altissimo"]] = Field(
        default="Baixo",
        description="Risco SO deste processo. NAO e o risco do merito (esse e camada 3)."
    )

    # Campo 5: trajetoria dentro do processo
    trajetoria_dentro_processo: Literal["estavel", "deteriorando", "melhorando", "indefinida"] = Field(
        default="indefinida",
        description="Sentido da evolucao do risco ao longo das movs deste processo",
    )

    # Campo 6: peca-pivo candidata
    peca_pivo_candidata: PecaPivoCandidata = Field(default_factory=PecaPivoCandidata)

    # Campo 7: valores
    valor_em_disputa: Optional[float] = Field(
        default=None,
        description="Melhor evidencia de valor em disputa (BRL). null se nao identificavel.",
    )
    valor_garantia: Optional[float] = Field(
        default=None,
        description="Valor da apolice/garantia depositada neste processo (BRL). null se nao identificavel.",
    )

    # Meta
    movs_processed: int = Field(default=0, description="Numero de mov_factsheets considerados")
    confianca: float = Field(default=0.7, ge=0.0, le=1.0)
    evidence_artifacts: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Lista de {mov_id, snippet, weight} citando movs que sustentam a sintese",
    )


# ── Request / Response ────────────────────────────────────────────────────


class MovFactSheetMin(BaseModel):
    """Versao reduzida do MovFactSheetCard pra alimentar processo_synthesis.

    O processo_synthesis nao precisa de TODOS os 13 campos -- soh os essenciais
    pra sintese. Mas aceita o card completo (campos extra sao ignorados).
    """

    mov_id: str
    data: Optional[str] = None
    resumo_ato: Optional[str] = None
    categoria: Optional[str] = None
    relevancia_merito: Optional[str] = None
    decisao: Optional[dict[str, Any]] = None
    evento_garantia: Optional[dict[str, Any]] = None
    status_garantia_pos_mov: Optional[str] = None
    tipo_garantia: Optional[str] = None
    delta_risco: Optional[dict[str, Any]] = None
    valores: Optional[dict[str, Any]] = None
    peca_pivo: Optional[dict[str, Any]] = None
    proximos_passos: Optional[list[str]] = None

    model_config = {"extra": "ignore"}


class ApoliceContextMin(BaseModel):
    """Resumo apolice card pra contexto."""

    numero_apolice: Optional[str] = None
    seguradora: Optional[str] = None
    valor_is: Optional[float] = None
    apresentada: Optional[bool] = None
    aceita: Optional[bool] = None
    is_central_for_merito: bool = False

    model_config = {"extra": "ignore"}


class AutosRawExcerpt(BaseModel):
    """Trecho raw do autos.zip pra alimentar processo_synthesis quando
    mov_factsheet nao tem doc_text (DD6 v6_meritos rev2).

    Padrao: primeiras 10 paginas (peticao inicial) + ultimas 50 (decisoes recentes).
    Cap absoluto: 60 paginas ou 60k chars.
    """

    text: str = Field(description="Texto extraido do autos.zip com separadores --- Pagina X/N ---")
    total_pages: int = 0
    pages_used: int = 0
    truncated: bool = False
    source: str = Field(default="lawsuit_pdfs_extraction", description="origem do PDF (lawsuit_pdfs ou outra)")


class ProcessoSynthesisRequest(BaseModel):
    processo_numero: str
    classe: Optional[str] = None
    classe_cnj_code: Optional[int] = None
    polo_ativo: Optional[str] = None
    polo_passivo: Optional[str] = None
    role_no_merito: Optional[Literal["principal", "conexo"]] = None
    mov_factsheets: list[MovFactSheetMin] = Field(default_factory=list)
    apolices: list[ApoliceContextMin] = Field(default_factory=list)
    autos_raw_excerpt: Optional[AutosRawExcerpt] = Field(
        default=None,
        description="DD6 rev2: trecho raw autos.zip pros 207/237 procs com extraction_completed",
    )
    model: Optional[str] = None
    provider: Optional[str] = None


class ProcessoSynthesisResponse(BaseModel):
    card: ProcessoSynthesisCard
    raw_response: Optional[str] = None
    usage: Optional[dict[str, Any]] = None

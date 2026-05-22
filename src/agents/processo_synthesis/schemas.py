"""Pydantic schemas pro processo_synthesis agent (engine v6_meritos camada 2).

Output cabe em leads.dossier_artifacts com kind='processo_synthesis'.

Spec canonica do plano: c:/Users/Eltonxp/.claude/plans/risk-engine-v6-meritos.md
"""

from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


# ── Sub-objetos ───────────────────────────────────────────────────────────


class DecisaoVigente(BaseModel):
    """Decisao judicial atualmente em vigor neste processo.

    Literais foram afrouxados pra Optional[str] (LLM gera valores fora-da-lista
    ocasionalmente; melhor recordar que falhar parse).
    """

    sentido: Optional[str] = None  # ideal: favoravel | desfavoravel | parcial | neutro
    instancia: Optional[str] = None  # ideal: 1g | 2g | stj | stf
    natureza: Optional[str] = None  # ideal: procedente | improcedente | parcialmente_procedente | extinto_sem_merito | homologatoria | interlocutoria
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
    evento: Optional[str] = None  # ideal: apresentacao | aceitacao | recusa | levantamento | substituicao | reforço
    tipo_garantia: Optional[str] = None  # ideal: seguro_garantia | fianca_bancaria | carta_fianca | deposito_judicial | penhora | fiduciaria | outras
    status_pos: Optional[str] = None  # ideal: apresentado | aceito | recusado | levantado | substituido | nenhum
    motivo_recusa: Optional[str] = None


class PecaPivoCandidata(BaseModel):
    """Candidata a peca-pivo dentro deste processo (input pro merito_synthesis decidir)."""

    mov_id: Optional[str] = None
    data: Optional[str] = None
    motivo: Optional[str] = Field(
        default=None,
        description="Por que esta mov define o estado atual do processo",
    )


class ProbabilidadeExito(BaseModel):
    """Probabilidade do CONTRIBUINTE (tomador) ter exito no processo.

    Matriz Daycoval 2026-05-21. Per-tipo (fiscal | trabalhista | civel) com
    criterios objetivos da planilha 'Matriz de Risco - Garantias Judiciais'.

    Conceitualmente DIFERENTE de risco_processo_intermediario:
    - prob_exito = ponto de vista juridico (chance do contribuinte ganhar)
    - risco_processo = ponto de vista da seguradora (chance de acionamento)
    Sao inversamente correlacionados mas nao 100%: tempo ate transito,
    substituicao de garantia, transacao tambem entram no risco.

    A camada 3 (merito_synthesis) usa probabilidade_exito como input forte
    pro risco final do merito.

    Literais afrouxados pra Optional[str] (LLM ocasionalmente gera valores
    fora da lista; defensive default).
    """

    classificacao: Optional[str] = Field(
        default=None,
        description="provavel | possivel | poucas_chances | remota. Pesos respectivos: 1.0 / 0.7 / 0.4 / 0.0001",
    )
    score: Optional[float] = Field(
        default=None,
        description="Peso numerico (1.0 / 0.7 / 0.4 / 0.0001) — espelha classificacao",
    )
    criterios_aplicados: list[str] = Field(
        default_factory=list,
        description="Bullets dos criterios objetivos da matriz Daycoval que sustentam a classificacao (audit trail juridico). Ex: ['Materia exclusivamente de direito favoravel ao Tomador']",
    )
    justificativa: Optional[str] = Field(
        default=None,
        description="1-3 frases PT-BR amarrando os criterios ao caso concreto",
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
    role_no_merito: Optional[str] = Field(
        default=None,
        description="Echo do role declarado no input (do mapeamento merito_membros). Ideal: 'principal' | 'conexo'",
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
    risco_processo_intermediario: Optional[str] = Field(
        default="Baixo",
        description="Risco SO deste processo (Baixo|Medio|Alto|Altissimo). NAO e o risco do merito (esse e camada 3)."
    )

    # Campo 5: trajetoria dentro do processo
    trajetoria_dentro_processo: Optional[str] = Field(
        default="indefinida",
        description="Sentido da evolucao (estavel|deteriorando|melhorando|indefinida)",
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

    # Campo 8: tipo judicial (determinado upstream por classify_tipo_judicial)
    tipo_judicial: Optional[str] = Field(
        default="civel",
        description="Tipo do processo (echo do request). Define qual matriz Daycoval aplicar. Valores ideais: fiscal | trabalhista | civel",
    )

    # Campo 9: probabilidade de exito (Matriz Daycoval 2026-05-21)
    probabilidade_exito: ProbabilidadeExito = Field(
        default_factory=ProbabilidadeExito,
        description="Probabilidade do tomador ter exito. LLM aplica os criterios objetivos da matriz Daycoval correspondente ao tipo_judicial. Default vazio quando LLM nao retorna (audit no campo classificacao=null).",
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


class DayFactSheetMin(BaseModel):
    """Subset do DayFactsheetCard pra alimentar processo_synthesis.

    Day_factsheet eh camada 1 alternativa quando proc tier=Degradado-Dia:
    1 card por DIA agregando movs+docs sem FK nativa doc<->mov. O L2 consome
    AO LADO dos mov_factsheets (intra-proc mixed tier — vide memory
    engine-v6-pipeline-quality-tiers).
    """

    date: Optional[str] = None
    resumo_dia: Optional[str] = None
    eventos: Optional[list[dict[str, Any]]] = None
    decisao_do_dia: Optional[dict[str, Any]] = None
    evento_garantia_do_dia: Optional[dict[str, Any]] = None
    relevancia_para_merito: Optional[str] = None
    docs_considerados: Optional[list[str]] = None
    confianca: Optional[float] = None

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


class MonolithFactsheetMin(BaseModel):
    """Subset do MonolithFactsheetCard (camada 1 tier monolitico) pra alimentar
    processo_synthesis.

    Full-RAG (memory engine-v6-pipeline-quality-tiers): substitui o legacy
    AutosRawExcerpt + DocAutos no L2. L1 monolith_factsheet ja sintetizou o
    PDF inteiro em campos estruturados — L2 consome esse card, nao o raw.
    """

    processo_numero: Optional[str] = None
    resumo_executivo: Optional[str] = None
    decisao_vigente: Optional[dict[str, Any]] = None
    eventos_principais: Optional[list[dict[str, Any]]] = None
    lifecycle_garantia: Optional[list[dict[str, Any]]] = None
    valor_em_disputa: Optional[float] = None
    valor_garantia: Optional[float] = None
    peca_pivo: Optional[dict[str, Any]] = None
    proximos_passos_provaveis: Optional[list[str]] = None
    confianca: Optional[float] = None
    pages_used: Optional[int] = None

    model_config = {"extra": "ignore"}


class ProcessoSynthesisRequest(BaseModel):
    processo_numero: str
    classe: Optional[str] = None
    classe_cnj_code: Optional[int] = None
    polo_ativo: Optional[str] = None
    polo_passivo: Optional[str] = None
    role_no_merito: Optional[Literal["principal", "conexo"]] = None
    tipo_judicial: Literal["fiscal", "trabalhista", "civel"] = Field(
        default="civel",
        description="Determinado upstream por garantis_shared.cnj_utils.classify_tipo_judicial(assunto, tribunal, classe_codigo). Caller resolve e passa.",
    )
    mov_factsheets: list[MovFactSheetMin] = Field(default_factory=list)
    day_factsheets: list[DayFactSheetMin] = Field(
        default_factory=list,
        description="Cards camada 1 alternativa (1 por dia) quando proc tier=por_dia. "
                    "Consumir junto com mov_factsheets (intra-proc mixed tier).",
    )
    monolith_factsheet: Optional[MonolithFactsheetMin] = Field(
        default=None,
        description="Card camada 1 tier monolitico — sintese do PDF inteiro. "
                    "Quando present, substitui o legacy autos_raw_excerpt + documents_dos_autos.",
    )
    apolices: list[ApoliceContextMin] = Field(default_factory=list)
    model: Optional[str] = None
    provider: Optional[str] = None


class ProcessoSynthesisResponse(BaseModel):
    card: ProcessoSynthesisCard
    # dict[str,str] desde split em 2 LLM calls: {"synthesis": ..., "prob_exito": ...}
    raw_response: Optional[dict[str, Any]] = None
    llm_raw_prompt: Optional[dict[str, Any]] = None
    prompt_version: Optional[str] = None
    usage: Optional[dict[str, Any]] = None

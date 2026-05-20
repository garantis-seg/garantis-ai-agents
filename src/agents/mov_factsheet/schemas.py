"""Pydantic schemas pro mov_factsheet agent (engine v6_meritos).

Output rico (13 campos) que substitui o mov_summarizer simples. Cabe em
leads.dossier_artifacts com kind='mov_factsheet'.

Spec canonica do plano: c:/Users/Eltonxp/.claude/plans/risk-engine-v6-meritos.md
"""

from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


# ── Sub-objetos ───────────────────────────────────────────────────────────


class DecisaoBlock(BaseModel):
    """Decisao processual presente na mov."""

    tem_decisao: bool = Field(default=False, description="True se a mov contem uma decisao judicial")
    sentido: Optional[Literal["favoravel", "desfavoravel", "parcial", "neutro"]] = Field(
        default=None,
        description="Sentido do ponto de vista do TOMADOR (executado/embargante/impetrante)",
    )
    instancia: Optional[Literal["1g", "2g", "stj", "stf"]] = None
    natureza: Optional[Literal[
        "procedente", "improcedente", "parcialmente_procedente",
        "extinto_sem_merito", "homologatoria", "interlocutoria",
    ]] = None
    transito_certificado: bool = False


class EventoGarantia(BaseModel):
    """Evento envolvendo a garantia/apolice nesta mov."""

    tipo: Literal[
        "apresentacao", "aceitacao", "recusa", "levantamento",
        "substituicao", "reforço", "nenhum",
    ] = Field(default="nenhum")
    motivo: Optional[str] = Field(
        default=None,
        description="Quando tipo=recusa: motivo explicito (ex: 'valor insuficiente'). null caso contrario.",
    )


class CDABlock(BaseModel):
    """CDAs/inscricoes em divida ativa mencionadas na mov."""

    numeros: list[str] = Field(default_factory=list, description="Numeros literais das CDAs mencionadas")
    ente: Optional[Literal["estadual", "municipal", "federal_pgfn"]] = None
    tributo: Optional[str] = Field(default=None, description="ICMS, ISS, IPVA, etc.")
    valor_total: Optional[float] = Field(default=None, description="Valor total em BRL quando explicito")


class ApoliceBlock(BaseModel):
    """Apolice envolvida nesta mov especifica."""

    numero: Optional[str] = None
    apresentada: Optional[bool] = Field(default=None, description="True se a mov registra apresentacao")
    aceita: Optional[bool] = Field(default=None, description="True se aceita pelo juizo, False se recusada")


class DeltaRisco(BaseModel):
    """Como esta mov alterou o risco do processo/merito vs o estado anterior."""

    mudou: bool = Field(default=False, description="True se esta mov muda materialmente o risco")
    direcao: Optional[Literal["aumentou", "diminuiu", "inalterado"]] = None
    motivo: Optional[str] = Field(
        default=None,
        description="1 frase PT-BR explicando POR QUE mudou (ou nao)",
    )


class ValoresBlock(BaseModel):
    """Valores monetarios extraidos da mov."""

    valor_causa: Optional[float] = None
    valor_debito_executado: Optional[float] = None
    valor_garantia: Optional[float] = None


class PecaPivo(BaseModel):
    """Indica se esta mov e candidata a peca-pivo do processo/merito."""

    e_pivo: bool = Field(default=False)
    motivo: Optional[str] = Field(
        default=None,
        description="Por que esta mov e (ou nao) pivo. null se e_pivo=false e motivo trivial.",
    )


# ── Output card principal ─────────────────────────────────────────────────


class MovFactSheetCard(BaseModel):
    """FactSheet rico de uma movimentacao. 13 campos.

    Cabe em dossier_artifacts.summary com kind='mov_factsheet'.

    Diferente de MovCardSummary (kind='movimentacao'), este card carrega:
    - Estrutura tipada por evento de seguro-garantia (apresentacao/aceitacao/recusa)
    - Delta de risco (sinal explicito de mudanca)
    - Peca-pivo flag (input pra processo_synthesis decidir destaque)
    - Valores monetarios extraidos
    - Proximos passos previstos

    Usado pela engine v6_meritos como camada 1 de 3.
    """

    # Identidade (eco do input)
    mov_id: str = Field(description="ID estavel da fonte")
    data: Optional[str] = Field(default=None, description="YYYY-MM-DD da mov")
    tipo_origem: Optional[str] = Field(
        default=None,
        description="Tipo bruto da fonte (ex: 'PUBLICACAO', 'DECISAO_INTERLOCUTORIA')",
    )

    # Campo 1: Resumo + categoria
    resumo_ato: str = Field(description="~50 palavras PT-BR explicando o ato + anexos + proximo passo")
    categoria: Literal[
        "decisao_merito", "decisao_interlocutoria", "sentenca", "acordao",
        "despacho", "peticao", "publicacao", "intimacao", "certidao",
        "ato_ordinatorio", "carga", "baixa", "conclusao", "outros",
    ] = Field(description="Categoria canonica do ato")

    # Campo 2: Relevancia pro merito
    relevancia_merito: Literal["alta", "media", "baixa", "ruido"] = Field(
        description="Quanto este ato influencia a tese/merito do processo principal"
    )

    # Campo 3: Decisao (sub-objeto)
    decisao: DecisaoBlock = Field(default_factory=DecisaoBlock)

    # Campo 4: Evento de seguro-garantia
    evento_garantia: EventoGarantia = Field(default_factory=EventoGarantia)

    # Campo 5: Status da garantia pos-mov
    status_garantia_pos_mov: Literal[
        "apresentado", "aceito", "recusado", "levantado", "substituido", "nenhum",
    ] = Field(default="nenhum")

    # Campo 6: Tipo da garantia
    tipo_garantia: Literal[
        "seguro_garantia", "fianca_bancaria", "carta_fianca",
        "deposito_judicial", "penhora", "fiduciaria", "outras", "nenhum",
    ] = Field(default="nenhum")

    # Campo 7: CDA
    cda: CDABlock = Field(default_factory=CDABlock)

    # Campo 8: Apolice
    apolice: ApoliceBlock = Field(default_factory=ApoliceBlock)

    # Campo 9: Delta de risco
    delta_risco: DeltaRisco = Field(default_factory=DeltaRisco)

    # Campo 10: Valores
    valores: ValoresBlock = Field(default_factory=ValoresBlock)

    # Campo 11: Peca-pivo
    peca_pivo: PecaPivo = Field(default_factory=PecaPivo)

    # Campo 12: Proximos passos
    proximos_passos: list[str] = Field(
        default_factory=list,
        description="Acoes esperadas a partir deste ato (ex: 'aguardar manifestacao da exequente')",
    )

    # Campo 13: Datas/conexos/confianca
    data_real_ato: Optional[str] = Field(
        default=None,
        description="YYYY-MM-DD do ato real se diferir da data de publicacao",
    )
    processos_conexos_mencionados: list[str] = Field(
        default_factory=list,
        description="CNJs (formatados ou raw) mencionados no texto",
    )
    confianca: float = Field(
        default=0.7,
        ge=0.0, le=1.0,
        description="Confianca do LLM nesta classificacao (0-1)",
    )


# ── Request / Response ────────────────────────────────────────────────────


class MovInput(BaseModel):
    mov_id: str
    data: Optional[str] = None
    tipo: Optional[str] = None
    texto: str


class ProcessoContext(BaseModel):
    """Contexto minimo do processo pra desambiguar mov isolada."""

    cnj: str
    classe: Optional[str] = None
    classe_cnj_code: Optional[int] = None
    polo_ativo: Optional[str] = None
    polo_passivo: Optional[str] = None


class DocAnexado(BaseModel):
    """1 documento anexado a esta movimentacao. Text ja extraido upstream
    (jusbrasil text_content / Gemini multimodal backfill F-0.5b)."""

    doc_key: str = Field(description="ID do doc no provider")
    titulo: Optional[str] = None
    tipo: Optional[str] = Field(default=None, description="SENTENCA | DESPACHO | CERTIDAO | ACORDAO | ...")
    data_documento: Optional[str] = Field(default=None, description="YYYY-MM-DD do doc se diferir da mov")
    paginas: Optional[int] = None
    text_content: str = Field(description="Texto extraido do PDF/HTML")
    text_truncated: bool = Field(
        default=False,
        description="True se cap de chars foi aplicado upstream",
    )
    provider: Optional[str] = Field(
        default=None,
        description="'jusbrasil' | 'escavador' | 'proprio'",
    )


class FallbackContext(BaseModel):
    """Contexto auxiliar quando mov NAO tem doc anexado (rota fallback DD4)."""

    processo_resumo_ia: Optional[str] = Field(
        default=None,
        description="Resumo IA do processo (leads.processos.resumo_ia) cap 1k chars",
    )
    mov_anterior_resumo: Optional[str] = Field(
        default=None,
        description="resumo_ato do mov_factsheet anterior por data ASC",
    )
    mov_anterior_categoria: Optional[str] = None
    distance_dias_mov_anterior: Optional[int] = Field(
        default=None,
        description="Dias entre data da mov anterior e esta",
    )


class MovFactSheetRequest(BaseModel):
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


class MovFactSheetResponse(BaseModel):
    card: MovFactSheetCard
    raw_response: Optional[str] = None
    usage: Optional[dict[str, Any]] = None

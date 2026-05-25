"""Pydantic schemas pro merito_synthesis agent (engine v6_meritos camada 3).

Output PRIMARIO da engine v6 - risco + justificativa + trajetoria por merito.
Cabe em monitoramento.risk_snapshots + dossier_artifacts kind='merito_synthesis'.

Spec canonica: c:/Users/Eltonxp/.claude/plans/risk-engine-v6-meritos.md
"""

from typing import Any, Literal, Optional
from pydantic import BaseModel, Field, field_validator


# ── Sub-objetos ───────────────────────────────────────────────────────────


class DecisaoAtual(BaseModel):
    """Decisao judicial atualmente vigente no merito (do processo mais relevante).

    Literais afrouxados pra Optional[str] (LLM gera valores fora-da-lista
    ocasionalmente).
    """

    sentido: Optional[str] = None  # ideal: favoravel | desfavoravel | parcial | neutro
    instancia: Optional[str] = None  # ideal: 1g | 2g | stj | stf
    natureza: Optional[str] = None  # ideal: procedente | improcedente | parcialmente_procedente | extinto_sem_merito | homologatoria | interlocutoria
    data: Optional[str] = Field(default=None, description="YYYY-MM-DD")
    processo_de_origem: Optional[str] = Field(
        default=None,
        description="CNJ do processo que carrega esta decisao (principal ou conexo)",
    )
    transito_certificado: bool = False
    recorrida: bool = False


class CicloGarantiaEvent(BaseModel):
    """1 evento cross-processo no ciclo da garantia/apolice neste merito."""

    data: Optional[str] = None
    processo_numero: Optional[str] = None
    evento: Optional[str] = None  # ideal: apresentacao | aceitacao | recusa | levantamento | substituicao | reforço
    tipo_garantia: Optional[str] = None
    status_pos: Optional[str] = None  # ideal: apresentado | aceito | recusado | levantado | substituido | nenhum
    motivo_recusa: Optional[str] = None


class PecaPivoMerito(BaseModel):
    """A movimentacao mais decisiva do merito inteiro (cross-processo).

    `mov_id` aceita int OR str — Gemini retorna inteiro quando o mov_id na
    timeline e numerico (ex: 27283057972), causando ValidationError quando
    schema exigia str. Coerce via validator pra normalizar str.
    """

    processo_numero: Optional[str] = None
    mov_id: Optional[str] = None
    data: Optional[str] = None
    motivo: Optional[str] = Field(
        default=None,
        description="1-2 frases explicando por que esta mov define o estado do merito",
    )

    @field_validator("mov_id", mode="before")
    @classmethod
    def _coerce_mov_id(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        return str(v) if not isinstance(v, str) else v


class ProbabilidadeExitoMerito(BaseModel):
    """Probabilidade de Exito agregada do merito (Matriz Daycoval).

    Agregacao default V1: media ponderada por valor_em_disputa dos processos
    'principal' (conexos contam metade). Pode evoluir pra peso especial de
    peca-pivo apos testes (decisao open 2026-05-21).

    Score numerico (0.0001 a 1.0) entra como FATOR no risco de acionamento
    da Camada 3. Inversao monotonica: prob_exito alta → risco baixo.
    """

    classificacao_agregada: Optional[str] = Field(
        default=None,
        description="Bucket equivalente ao score (provavel|possivel|poucas_chances|remota)",
    )
    score_agregado: Optional[float] = Field(
        default=None,
        ge=0.0, le=1.0,
        description="Media ponderada por valor_em_disputa dos processos. Espelha classificacao.",
    )
    metodo_agregacao: str = Field(
        default="media_ponderada_valor_disputa",
        description="Metodo usado (V1: media ponderada). Audit trail.",
    )
    breakdown_por_processo: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Lista de {processo_numero, role, classificacao, score, peso_aplicado, valor_em_disputa}",
    )
    contribuicao_no_risco: Optional[str] = Field(
        default=None,
        description="1 frase PT-BR explicando como a prob_exito agregada influenciou o risco final",
    )


class EvidenceArtifact(BaseModel):
    """Citacao de card consumido pra sustentar a sintese."""

    kind: Optional[str] = None  # ideal: processo_synthesis | mov_factsheet | apolice | conexo | cda | aiim | tomador | merito
    ref: Optional[str] = Field(default=None, description="processo_numero, mov_id, merito_id, ou outro identificador")
    snippet: Optional[str] = Field(default=None, description="Trecho citado (~200 chars)")
    weight: Optional[str] = None  # ideal: high | medium | low


# ── Output card principal ─────────────────────────────────────────────────


class MeritoSynthesisCard(BaseModel):
    """Sintese do MERITO inteiro - output primario da engine v6_meritos.

    Persistido em monitoramento.risk_snapshots E em dossier_artifacts kind='merito_synthesis'.

    A camada 3 e o consumo final - quando este card e gerado, fecha a engine.
    """

    merito_id: int
    merito_context: Literal["monit_poletto", "global"] = "monit_poletto"

    # Output principal - risco + justificativa
    risco: Optional[str] = Field(
        default="Baixo",
        description="Risco de acionamento da apolice no MERITO (Baixo|Medio|Alto|Altissimo)"
    )
    justificativa: Optional[str] = Field(
        default="",
        description="2-4 paragrafos PT-BR citando evidencias dos cards consumidos"
    )
    narrativa_executiva: Optional[str] = Field(
        default=None,
        description="1 frase resumindo o estado do merito pro time comercial",
    )

    # Estado
    decisao_atual: DecisaoAtual = Field(default_factory=DecisaoAtual)
    ciclo_garantia: list[CicloGarantiaEvent] = Field(
        default_factory=list,
        description="Timeline cross-processo dos eventos da garantia",
    )

    # Valores agregados
    valor_em_disputa_melhor_evidencia: Optional[float] = Field(
        default=None,
        description="Soma ou maior dos processo.valor_em_disputa (BRL)",
    )
    valor_garantia_melhor_evidencia: Optional[float] = Field(
        default=None,
        description="Soma dos valor_garantia das apolices atreladas (BRL)",
    )

    # Peca-pivo
    peca_pivo_merito: PecaPivoMerito = Field(default_factory=PecaPivoMerito)

    # Probabilidade de Exito agregada (Matriz Daycoval 2026-05-21)
    probabilidade_exito_merito: ProbabilidadeExitoMerito = Field(
        default_factory=ProbabilidadeExitoMerito,
        description="Agregacao das prob_exito dos processos do merito. Input forte pro risco final.",
    )

    # Forward
    proximos_passos_provaveis: list[str] = Field(default_factory=list)

    # Trajetoria - computada externamente baseada em snapshot anterior
    # (LLM NAO preenche esses campos; orchestrator setta antes de persistir)
    trajetoria: Optional[str] = None  # ideal: estavel | piorou | melhorou | primeira_classificacao
    trajetoria_motivo: Optional[str] = None

    # Meta
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    evidence_artifacts: list[EvidenceArtifact] = Field(default_factory=list)
    cards_index: dict[str, Any] = Field(
        default_factory=dict,
        description="Contagem de cards consumidos por kind. Aceita Any porque "
                    "Gemini ocasionalmente retorna dict aninhado ao inves de int "
                    "(ex: {'processo_X': {'mov_factsheets': 12}}); validator "
                    "normaliza pra int via _normalize_cards_index_value below.",
    )

    @field_validator("cards_index", mode="before")
    @classmethod
    def _normalize_cards_index(cls, v: Any) -> dict[str, Any]:
        if not isinstance(v, dict):
            return {}
        out: dict[str, Any] = {}
        for key, val in v.items():
            if isinstance(val, int):
                out[key] = val
            elif isinstance(val, dict):
                # Gemini retornou dict aninhado — somar valores int filhos
                total = sum(x for x in val.values() if isinstance(x, int))
                out[key] = total
            else:
                try:
                    out[key] = int(val)
                except (TypeError, ValueError):
                    out[key] = 0
        return out


# ── Request / Response ────────────────────────────────────────────────────


class ProcessoSynthesisMin(BaseModel):
    """Subset do ProcessoSynthesisCard pra alimentar merito_synthesis."""

    processo_numero: str
    classe: Optional[str] = None
    role_no_merito: Optional[Literal["principal", "conexo"]] = None
    estado_processual: Optional[str] = None
    decisao_vigente: Optional[dict[str, Any]] = None
    lifecycle_garantia: Optional[list[dict[str, Any]]] = None
    risco_processo_intermediario: Optional[str] = None
    trajetoria_dentro_processo: Optional[str] = None
    peca_pivo_candidata: Optional[dict[str, Any]] = None
    valor_em_disputa: Optional[float] = None
    valor_garantia: Optional[float] = None
    tipo_judicial: Optional[Literal["fiscal", "trabalhista", "civel"]] = None
    probabilidade_exito: Optional[dict[str, Any]] = Field(
        default=None,
        description="Card de probabilidade_exito do processo (Matriz Daycoval). Camada 3 agrega.",
    )

    model_config = {"extra": "ignore"}


class CDACardMin(BaseModel):
    """CDA card (kind='cda') pra contexto de divida ativa no merito."""

    cda_number: Optional[str] = None
    valor: Optional[float] = None
    tipo_tributo: Optional[str] = None
    ente: Optional[str] = None
    data_inscricao: Optional[str] = None
    aiim_number_associado: Optional[str] = None
    notes: Optional[str] = None

    model_config = {"extra": "ignore"}


class AIIMCardMin(BaseModel):
    """AIIM card (kind='aiim') pra contexto administrativo no merito."""

    tipo: Optional[str] = None
    numero: Optional[str] = None
    relacao: Optional[str] = None
    contexto_snippet: Optional[str] = None
    justificativa: Optional[str] = None

    model_config = {"extra": "ignore"}


class TomadorCardMin(BaseModel):
    """Tomador card (kind='tomador') agregado por cnpj_basico."""

    nome: Optional[str] = None
    cnpj_basico: Optional[str] = None
    historico: Optional[dict[str, Any]] = None
    alertas: Optional[list[str]] = None
    valor_total_garantido: Optional[float] = None

    model_config = {"extra": "ignore"}


class JurisprudenciaMin(BaseModel):
    """Jurisprudencia da tese canonica do merito."""

    tese_nome: Optional[str] = None
    tema_stj: Optional[str] = None
    tema_stf: Optional[str] = None
    resultado_majoritario: Optional[str] = None

    model_config = {"extra": "ignore"}


class ParadigmaMin(BaseModel):
    """Decisao paradigma da tese (1 row de ref.tese_decisao_individual).

    Loaded quando eh_paradigma=TRUE pra ancorar narrativa L3 com exemplos
    concretos (acordaos/sentencas firmes citaveis). Pre-filtrados por
    tese_canonica_id — tipo-consistent.

    `sentido` enum em DB: pro_contribuinte | pro_fazenda | dividida | outro.
    Strings passadas raw pro prompt (LLM entende contexto)."""

    tribunal: Optional[str] = None
    instancia: Optional[str] = None
    data_decisao: Optional[str] = None
    sentido: Optional[str] = None
    ementa_resumo: Optional[str] = None
    relator: Optional[str] = None

    model_config = {"extra": "ignore"}


class PreviousSnapshot(BaseModel):
    """Snapshot anterior de risco do mesmo merito (pra computar trajetoria)."""

    risco_anterior: Optional[str] = None
    classified_at_anterior: Optional[str] = None
    decisao_anterior: Optional[dict[str, Any]] = None


class MeritoSynthesisRequest(BaseModel):
    merito_id: int
    merito_context: Literal["monit_poletto", "global"] = "monit_poletto"
    titulo: Optional[str] = None
    tipo_principal: Optional[str] = None
    cnpj_principal: Optional[str] = None
    razao_social: Optional[str] = None

    # Cards consumidos
    processo_syntheses: list[ProcessoSynthesisMin] = Field(default_factory=list)
    tomador: Optional[TomadorCardMin] = None
    cdas: list[CDACardMin] = Field(default_factory=list)
    aiims: list[AIIMCardMin] = Field(default_factory=list)
    jurisprudencia: Optional[JurisprudenciaMin] = None
    paradigmas: list[ParadigmaMin] = Field(default_factory=list)

    # Trajetoria (passado pelo orchestrator antes da call)
    previous_snapshot: Optional[PreviousSnapshot] = None

    model: Optional[str] = None
    provider: Optional[str] = None


class MeritoSynthesisResponse(BaseModel):
    card: MeritoSynthesisCard
    raw_response: Optional[str] = None
    llm_raw_prompt: Optional[str] = None
    prompt_version: Optional[str] = None
    usage: Optional[dict[str, Any]] = None

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

    v2.1: APERTADO pra Literal[...] depois que L2 demonstrou que Optional[str]
    com response_schema causa loop infinito no decoder Gemini 2.5 Flash.
    Comentario antigo dizia "afrouxado porque LLM gera fora-da-lista" — isso
    era SEM response_schema. Com enforcement, Gemini respeita o enum.
    """

    sentido: Optional[Literal["favoravel", "desfavoravel", "parcial", "neutro"]] = Field(
        default=None,
        description="Sentido DO PONTO DE VISTA DO TOMADOR (Tomador=devedor/executado).",
    )
    instancia: Optional[Literal["1g", "2g", "stj", "stf"]] = Field(default=None)
    natureza: Optional[Literal[
        "procedente", "improcedente", "parcialmente_procedente",
        "extinto_sem_merito", "homologatoria", "interlocutoria",
    ]] = Field(default=None)
    data: Optional[str] = Field(default=None, description="YYYY-MM-DD")
    processo_de_origem: Optional[str] = Field(
        default=None,
        description="CNJ do processo que carrega esta decisao (principal ou conexo)",
    )
    transito_certificado: bool = False
    recorrida: bool = False


class CicloGarantiaEvent(BaseModel):
    """1 evento cross-processo no ciclo da garantia/apolice neste merito.

    v2.1: APERTADO pra Literal[...] (mesmo motivo de DecisaoAtual).
    """

    data: Optional[str] = None
    processo_numero: Optional[str] = None
    evento: Optional[Literal[
        "apresentacao", "aceitacao", "recusa", "levantamento",
        "substituicao", "reforço",
    ]] = None
    tipo_garantia: Optional[Literal[
        "seguro_garantia", "fianca_bancaria", "carta_fianca",
        "deposito_judicial", "penhora", "fiduciaria", "outras",
    ]] = None
    status_pos: Optional[Literal[
        "apresentado", "aceito", "recusado", "levantado", "substituido", "nenhum",
    ]] = None
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


class Citacao(BaseModel):
    """Liga um trecho da justificativa ao movimento DECISIVO que o sustenta — a
    movimentacao (com mov_id) que pesou na decisao de risco. Torna o fator de
    decisao explicito/auditavel e clicavel no front (salta pro movimento exato).

    O LLM emite trecho + processo_numero (que ele sabe fazer bem); o movimento_id
    e preenchido DETERMINISTICAMENTE pos-LLM (peca_pivo_candidata da camada 2 do
    processo) pra evitar transcricao de UUID pelo modelo. Ver materializer.
    """

    trecho: Optional[str] = Field(
        default=None,
        description=(
            "Trecho EXATO copiado da justificativa que nomeia o evento/decisao "
            "(ex: 'transito em julgado de decisao contraria a tese da empresa'). "
            "Copie literalmente — o front casa por substring."
        ),
    )
    processo_numero: Optional[str] = None
    movimento_id: Optional[str] = Field(
        default=None,
        description="mov_id do movimento decisivo daquele processo. Preenchido pelo codigo se ausente.",
    )

    @field_validator("movimento_id", mode="before")
    @classmethod
    def _coerce_movimento_id(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        return str(v) if not isinstance(v, str) else v


class BreakdownProcesso(BaseModel):
    """Breakdown agregacao prob_exito por processo do merito.

    Substitui o legacy list[dict[str, Any]] que Gemini rejeitava com
    'additionalProperties is not supported' quando exposto via response_schema.
    """

    processo_numero: Optional[str] = Field(default=None, description="CNJ do processo.")
    role: Optional[Literal["principal", "conexo"]] = Field(default=None)
    classificacao: Optional[Literal[
        "provavel", "possivel", "poucas_chances", "remota",
    ]] = None
    score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    peso_aplicado: Optional[float] = Field(
        default=None,
        description="Peso aplicado na agregacao (principal=1.0, conexo=0.5).",
    )
    valor_em_disputa: Optional[float] = None


class ProbabilidadeExitoMerito(BaseModel):
    """Probabilidade de Exito agregada do merito (Matriz Daycoval).

    Agregacao default V1: media ponderada por valor_em_disputa dos processos
    'principal' (conexos contam metade). Pode evoluir pra peso especial de
    peca-pivo apos testes (decisao open 2026-05-21).

    Score numerico (0.0001 a 1.0) entra como FATOR no risco de acionamento
    da Camada 3. Inversao monotonica: prob_exito alta → risco baixo.

    v2.1: APERTADO pra Literal[...] + breakdown_por_processo via Pydantic model
    concreto (BreakdownProcesso) em vez de dict[str, Any].
    """

    classificacao_agregada: Optional[Literal[
        "provavel", "possivel", "poucas_chances", "remota",
    ]] = Field(
        default=None,
        description="Bucket equivalente ao score (provavel=1.0/possivel=0.7/poucas_chances=0.4/remota=0.0001).",
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
    breakdown_por_processo: list[BreakdownProcesso] = Field(
        default_factory=list,
        description="Lista de breakdown por processo. Audit trail da agregacao.",
    )
    contribuicao_no_risco: Optional[str] = Field(
        default=None,
        description=(
            "1 frase PT-BR (texto pro ADVOGADO) explicando, em termos JURIDICOS, "
            "como a perspectiva de exito influenciou o risco final. NUNCA cite "
            "score/numero decimal, a palavra 'score', nomes internos (Daycoval/"
            "Poletto/Architecture D/matriz determ/sem nuance), rotulos snake_case "
            "(poucas_chances) nem codigos de template (T-B1). Ver <filtro_redacao_advogado>."
        ),
    )


class EvidenceArtifact(BaseModel):
    """Citacao de card consumido pra sustentar a sintese.

    v2.1: APERTADO pra Literal[...] em kind/weight.
    """

    kind: Optional[Literal[
        "processo_synthesis", "mov_factsheet", "apolice", "conexo",
        "cda", "aiim", "tomador", "merito",
    ]] = None
    ref: Optional[str] = Field(default=None, description="processo_numero, mov_id, merito_id, ou outro identificador")
    snippet: Optional[str] = Field(default=None, description="Trecho citado (~200 chars)")
    weight: Optional[Literal["high", "medium", "low"]] = None


class CardsIndexCount(BaseModel):
    """Contagem de cards consumidos por kind.

    Substitui dict[str, Any] (que gerava additionalProperties bug + Gemini
    ocasionalmente retornava dict aninhado). Schema fixo com fields known.
    Validator legacy em MeritoSynthesisCard ainda normaliza inputs legacy.
    """

    processo_synthesis: int = 0
    cda: int = 0
    aiim: int = 0
    tomador: int = 0
    jurisprudencia: int = 0
    paradigmas: int = 0
    apolice: int = 0
    mov_factsheet: int = 0


# ── Output card principal ─────────────────────────────────────────────────


class MeritoSynthesisCard(BaseModel):
    """Sintese do MERITO inteiro - output primario da engine v6_meritos.

    Persistido em monitoramento.risk_snapshots E em dossier_artifacts kind='merito_synthesis'.

    A camada 3 e o consumo final - quando este card e gerado, fecha a engine.
    """

    merito_id: int
    # Literal["monit_poletto","global"] pre-mig 20260528_2000; pos-merge so 'global'.
    # Mantido o tipo composto pra aceitar valores legacy do worker durante deploy window.
    merito_context: Literal["monit_poletto", "global"] = "global"

    # Output principal - risco + justificativa
    # PR7.1 (2026-05-31): adicionou 'Indeterminado' ao Literal. Quando Architecture D
    # mode=new + matriz determ retorna Indeterminado (factual + juris ambos null),
    # promote logic mantem o veredito LLM como fallback ao inves de forcar 'Baixo'.
    # Antes, schema rejeitava emit de Indeterminado mesmo quando matriz nao tem
    # sinal — agora pode emit explicito.
    risco: Optional[Literal["Baixo", "Medio", "Alto", "Altissimo", "Indeterminado"]] = Field(
        default="Baixo",
        description=(
            "Risco de acionamento da apolice no MERITO. Default = Baixo. So sobe pra "
            "Medio/Alto/Altissimo com sinal explicito documentado (vide PROTOCOLO DE "
            "RISCO BASE + ESCALA EXPLICITA no prompt). 'Indeterminado' permitido SO "
            "quando ambos factual e juris ausentes e LLM nao consegue desambiguar."
        ),
    )
    justificativa: Optional[str] = Field(
        default="",
        description=(
            "2-4 paragrafos PT-BR (texto pro ADVOGADO) citando evidencias. "
            "Paragrafo 1: estado factual. Paragrafo 2: aspectos suportivos. "
            "Paragrafo 3: justificativa do nivel vs nivel adjacente. Cite CNJs. "
            "NUNCA inclua jargao interno (score/decimal, snake_case, T-B1, "
            "Daycoval/Poletto/Architecture D, 'matriz determ/sem nuance', 'piso "
            "minimo', 'merito'+numero, mov_id). Ver <filtro_redacao_advogado>."
        ),
    )
    citacoes: list[Citacao] = Field(
        default_factory=list,
        description=(
            "Movimentos DECISIVOS por tras da justificativa: para cada decisao/"
            "evento concreto citado no texto (transito, sentenca adversa, acordao "
            "mantido, etc.), emita 1 Citacao com o TRECHO exato copiado da "
            "justificativa + o processo_numero. Liga a prosa ao ato real "
            "(auditavel + clicavel). NAO inventar; so eventos que estao na prosa."
        ),
    )
    narrativa_executiva: Optional[str] = Field(
        default=None,
        description="1 frase (pro ADVOGADO/time comercial) resumindo o estado do caso, em portugues juridico acessivel. SEM jargao interno (score, snake_case, T-XX, nomes de produto, 'piso minimo'). Ver <filtro_redacao_advogado>.",
    )

    # Estado
    decisao_atual: DecisaoAtual = Field(default_factory=DecisaoAtual)
    # ciclo_garantia REMOVIDO do output do LLM (2026-06-19): pedir pro LLM re-listar
    # eventos que JÁ damos a ele (no lifecycle_garantia dos processo_syntheses) fazia
    # o L3 LOOPAR numa lista runaway — 680046 gerava ~880 eventos / 145KB de JSON
    # malformado → parse fail → indeterminado (não-determinístico). Agora é montado
    # DETERMINISTICAMENTE em código (agent._assemble_ciclo_garantia) dos próprios
    # lifecycle_garantia do input → exato, bounded, sem degeneração. CicloGarantiaEvent
    # (acima) segue como contrato do shape persistido. Consumidor: snapshots.py usa
    # card.get("ciclo_garantia") (dict), não atributo tipado.

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
    trajetoria: Optional[Literal[
        "estavel", "piorou", "melhorou", "primeira_classificacao",
    ]] = None
    trajetoria_motivo: Optional[str] = None

    # Meta
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    evidence_artifacts: list[EvidenceArtifact] = Field(default_factory=list)
    cards_index: CardsIndexCount = Field(
        default_factory=CardsIndexCount,
        description=(
            "Contagem de cards consumidos por kind (schema fixo via CardsIndexCount). "
            "Validator legacy normaliza dict aninhado (Gemini ocasionalmente retornava "
            "{'processo_X': {'mov_factsheets': 12}}) somando os ints filhos."
        ),
    )

    @field_validator("cards_index", mode="before")
    @classmethod
    def _normalize_cards_index(cls, v: Any) -> Any:
        """Aceita dict legacy + normaliza pra CardsIndexCount.

        Forma legacy: dict[str, Any] com keys dinamicos e values int|dict.
        Pydantic constroi CardsIndexCount a partir desse dict (campos extras
        sao ignorados; valores aninhados sao somados).
        """
        if v is None or isinstance(v, CardsIndexCount):
            return v
        if not isinstance(v, dict):
            return {}
        out: dict[str, Any] = {}
        # Filter pra keys conhecidos no CardsIndexCount + normaliza values
        valid_keys = set(CardsIndexCount.model_fields.keys())
        for key, val in v.items():
            if key not in valid_keys:
                continue
            if isinstance(val, int):
                out[key] = val
            elif isinstance(val, dict):
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
    # PR6 Architecture D — orthogonal paths emitidos pelo L2 (PR3 schema).
    # Camada 3 le esses pra rodar A/B test (factual_only / juris_only / mixed /
    # derived_only). Default None quando card materializado pre-PR3 OU L2
    # nao conseguiu derivar — L3 trata None como Indeterminado (fallback).
    risco_factual: Optional[Literal[
        "Baixo", "Medio", "Alto", "Altissimo", "Indeterminado",
    ]] = Field(
        default=None,
        description="Risco derivado SO de estado + Matriz Daycoval (Architecture D).",
    )
    risco_jurisprudencial: Optional[Literal[
        "Baixo", "Medio", "Alto", "Altissimo", "Indeterminado",
    ]] = Field(
        default=None,
        description="Risco derivado SO de tese + ementas (Architecture D).",
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


# v2.5 (2026-06-12): JurisprudenciaMin REMOVIDO — dead code desde a v2.2
# (campo jurisprudencia saiu do MeritoSynthesisRequest; o unico consumidor
# era _summarize_jurisprudencia, tambem dead, deletado junto).


# PR7.2 (2026-05-31): ParadigmaMin REMOVIDO. Curadoria interna de paradigmas
# Poletto (ref.tese_decisao_individual, 209 rows curadas) dropada. Architecture
# D promote (mode=new) + LLM prompt rescrito assume papel jurisprudencial.


class PreviousSnapshot(BaseModel):
    """Snapshot anterior de risco do mesmo merito (pra computar trajetoria)."""

    risco_anterior: Optional[str] = None
    classified_at_anterior: Optional[str] = None
    decisao_anterior: Optional[dict[str, Any]] = None


class MeritoSynthesisRequest(BaseModel):
    merito_id: int
    # Literal["monit_poletto","global"] pre-mig 20260528_2000; pos-merge so 'global'.
    # Mantido o tipo composto pra aceitar valores legacy do worker durante deploy window.
    merito_context: Literal["monit_poletto", "global"] = "global"
    titulo: Optional[str] = None
    tipo_principal: Optional[str] = None
    cnpj_principal: Optional[str] = None
    razao_social: Optional[str] = None

    # Cards consumidos
    processo_syntheses: list[ProcessoSynthesisMin] = Field(default_factory=list)
    tomador: Optional[TomadorCardMin] = None
    cdas: list[CDACardMin] = Field(default_factory=list)
    aiims: list[AIIMCardMin] = Field(default_factory=list)
    # jurisprudencia removido — agora vive em L2 ps_card (regras J/J.1/J.2).
    # PR7.2 (2026-05-31): paradigmas: list[ParadigmaMin] REMOVIDO
    # (ref.tese_decisao_individual dropped).

    # Trajetoria (passado pelo orchestrator antes da call)
    previous_snapshot: Optional[PreviousSnapshot] = None

    model: Optional[str] = None
    provider: Optional[str] = None

    # PR6 Architecture D — A/B test bucket. None = legacy single-prompt.
    # Quando set, prompts.py injeta instrucao especifica por bucket pra
    # forcar L3 LLM a usar SO um subset dos sinais. Permite avaliar qual
    # arquitetura (factual_only / juris_only / mixed / derived_only)
    # acerta mais Poletto ground truth.
    bucket: Optional[Literal[
        "factual_only", "juris_only", "mixed", "derived_only",
    ]] = None

    # PR6 Architecture D — quando bucket="derived_only", o materializer L3
    # pre-calcula derived_aggregate via matriz determ 5x5 e injeta aqui pro
    # LLM justificar (NAO substituir). Ignorado em outros buckets.
    derived_aggregate_hint: Optional[Literal[
        "Baixo", "Medio", "Alto", "Altissimo", "Indeterminado",
    ]] = None

    # Defensive: extra fields ignored (cobre materializer legacy passando
    # `jurisprudencia` antes deste commit; safe pra rollouts staggered).
    model_config = {"extra": "ignore"}


class MeritoSynthesisCardOut(MeritoSynthesisCard):
    """MeritoSynthesisCard + ciclo_garantia. É o tipo do PARSE e da RESPOSTA HTTP.

    Decoupling (2026-06-19): o LLM usa MeritoSynthesisCard (base, SEM ciclo_garantia)
    como response_schema → não pode loopar re-listando os eventos (680046: ~880 eventos
    / 145KB malformado → indeterminado). O ciclo_garantia é montado em CÓDIGO
    (agent._assemble_ciclo_garantia) e vive SÓ aqui — senão o response_model (que tipa
    card por esta classe) o estriparia da resposta.
    """

    # list[dict], NÃO list[CicloGarantiaEvent]: o shape é controlado pelo _assemble, mas
    # os VALORES vêm do lifecycle real (evento pode ser 'acionamento'/'nenhum', 'reforco'
    # sem cedilha, etc.) — os Literals estritos de CicloGarantiaEvent rejeitariam dado
    # válido → ResponseValidationError 500. CicloGarantiaEvent segue como doc do shape.
    ciclo_garantia: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Timeline cross-processo da garantia — montada em código, NÃO pelo LLM.",
    )


class MeritoSynthesisResponse(BaseModel):
    card: MeritoSynthesisCardOut
    raw_response: Optional[str] = None
    llm_raw_prompt: Optional[str] = None
    prompt_version: Optional[str] = None
    usage: Optional[dict[str, Any]] = None
    # PR6 Architecture D — echo do bucket que rodou (pro materializer L3
    # persistir card['l3_ab_test'][bucket]).
    bucket: Optional[str] = None


# ── L2 PROSA — passe de redacao (2026-06-28) ──────────────────────────────
# "Codigo decide o risco, LLM redige." O risco JA foi decidido (holistico +
# guards determ.) e entra FIXO; este passe so verbaliza a prosa aplicando o
# <filtro_redacao_advogado> VERBATIM. Reusa todos os _build_*_block do prompt
# L3 (por isso RedacaoRequest e subclasse de MeritoSynthesisRequest — carrega
# os MESMOS fatos que o materializer ja monta no payload), so adicionando
# risco_final. Ver prompts.build_redacao_prompt + redacao.redact_merito_synthesis.


class RedacaoRequest(MeritoSynthesisRequest):
    """MeritoSynthesisRequest + o risco JA decidido (input imutavel do passe)."""

    risco_final: Literal["Baixo", "Medio", "Alto", "Altissimo"]


class RedacaoCard(BaseModel):
    """So a PROSA — o passe nao re-decide risco nem mexe em valores/agregados.

    Os campos espelham os que o <filtro_redacao_advogado> lista. Todos texto
    livre PT-BR (sem enum -> sem o loop do decoder Gemini com Literal). O
    materializer escreve cada um de volta no card persistido.
    """

    justificativa: Optional[str] = Field(
        default="",
        description=(
            "2-4 paragrafos PT-BR pro ADVOGADO. Paragrafo 1: estado factual. "
            "Paragrafo 2: aspectos suportivos. Paragrafo 3: por que este nivel e "
            "nao o adjacente. Cite CNJ. SEM jargao interno (ver filtro)."
        ),
    )
    narrativa_executiva: Optional[str] = Field(
        default=None,
        description="1 frase pro time comercial resumindo o estado do caso. SEM jargao interno.",
    )
    contribuicao_no_risco: Optional[str] = Field(
        default=None,
        description="1 frase JURIDICA: como a perspectiva de exito influenciou o risco. SEM score/numero.",
    )
    decisao_justificativa_breve: Optional[str] = Field(
        default=None,
        description="1 frase explicando a decisao vigente que governa o merito hoje.",
    )
    peca_pivo_motivo: Optional[str] = Field(
        default=None,
        description="1-2 frases: por que a peca-pivo define o estado do merito. Vazio se nao ha peca clara.",
    )
    proximos_passos_provaveis: list[str] = Field(
        default_factory=list,
        description="2-4 acoes esperadas pro merito, em portugues corrente.",
    )


class RedacaoResponse(BaseModel):
    card: RedacaoCard
    raw_response: Optional[str] = None
    llm_raw_prompt: Optional[str] = None
    prompt_version: Optional[str] = None
    usage: Optional[dict[str, Any]] = None
    # Diagnostico do guard: 'llm' (passou limpo), 'llm_retry' (vazou 1x, retry
    # limpou) ou 'template' (vazou 2x -> fallback determ.). prose_leak_cats =
    # categorias que vazaram no 1o output (telemetria de vazamento).
    prose_source: Literal["llm", "llm_retry", "template"] = "llm"
    prose_leak_cats: list[str] = Field(default_factory=list)

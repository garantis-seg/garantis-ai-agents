"""Pydantic schemas pro processo_synthesis agent (engine v6_meritos camada 2).

Output cabe em leads.dossier_artifacts com kind='processo_synthesis'.

Spec canonica do plano: c:/Users/Eltonxp/.claude/plans/risk-engine-v6-meritos.md
"""

from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


# ── Sub-objetos ───────────────────────────────────────────────────────────


class DecisaoVigente(BaseModel):
    """Decisao judicial atualmente em vigor neste processo.

    v2.1: APERTADO pra Literal[...] depois que descobrimos que Optional[str]
    com response_schema + descriptions longas causava loop infinito de \\n
    no Gemini 2.5 Flash (decoder sem ancora pra fechar o campo). Com Literal
    enum, decoder eh forcado a escolher dentro da lista — sem ambiguidade.

    Caveat historico: comentario anterior dizia "afrouxado porque LLM gera
    fora-da-lista" — isso era SEM response_schema. Com schema enforcement
    nativo, o Gemini respeita o enum.
    """

    sentido: Optional[Literal["favoravel", "desfavoravel", "parcial", "neutro"]] = Field(
        default=None,
        description=(
            "Sentido DO PONTO DE VISTA DO TOMADOR. Em EF: procedente=desfavoravel; "
            "em Embargos/MS/Anulatoria: procedente=favoravel. null quando nao ha decisao de merito."
        ),
    )
    instancia: Optional[Literal["1g", "2g", "stj", "stf"]] = Field(
        default=None,
        description="Instancia da decisao vigente.",
    )
    natureza: Optional[Literal[
        "procedente", "improcedente", "parcialmente_procedente",
        "extinto_sem_merito", "homologatoria", "interlocutoria",
    ]] = Field(
        default=None,
        description="Natureza juridica da decisao.",
    )
    data: Optional[str] = Field(default=None, description="YYYY-MM-DD da decisao")
    transito_certificado: bool = Field(
        default=False,
        description="True SO se ha mov certificando transito em julgado.",
    )
    recorrida: bool = Field(
        default=False,
        description="True se houve recurso interposto contra a decisao vigente.",
    )


class LifecycleGarantiaEvent(BaseModel):
    """Evento no ciclo de vida da garantia/apolice neste processo.

    v2.1: APERTADO pra Literal[...] (mesmo motivo de DecisaoVigente — evita
    loop do decoder Gemini sob response_schema).
    """

    data: Optional[str] = Field(default=None, description="YYYY-MM-DD")
    mov_id: Optional[str] = None
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


# PR7.2 (2026-05-31): TeseJurisprudenciaMin REMOVIDO. Curadoria interna
# (ref.tese_jurisprudencia base rate por tese×tribunal) substituida por
# JurisprudenciaExternaMin (provider externo jurisprudencias.ai). Architecture
# D modo new ja eh source-of-truth pro card.risco — L2 prompt nao injeta mais
# bloco <jurisprudencia> interno (so o <jurisprudencia_externa> quando
# JURISPRUDENCE_PATH_ENABLED != off).


class JurisprudenciaExternaMin(BaseModel):
    """Jurisprudencia externa da tese × tribunal via provider jurisprudencias.ai.

    Architecture D PR3 (2026-05-31). Populated quando flag JURISPRUDENCE_PATH_ENABLED
    != off + merito tem tese_canonica_id + tribunal cabe no provider (11 cortes).
    None quando flag off OR tese unavailable OR tribunal sem mapping (graceful).

    `top_decisions` traz ate 3 ementas (process_number / publication_date / excerpt /
    url) que o prompt L2 pode citar no field justificativa. cached=True quando veio
    do cache TTL 30d (sem chamar provider). source='provider' fixo em V1.
    """

    tribunal: Optional[str] = Field(
        default=None,
        description="Tribunal interno (TJSP/STJ/STF/TRF3/...) — mapeado pro provider court_id.",
    )
    resultado_majoritario: Optional[str] = Field(
        default=None,
        description=(
            "Heuristic tally: 'pro_contribuinte' (provider mostra majoritariamente "
            "favoravel ao Tomador) | 'pro_fazenda' (majoritariamente desfavoravel) | "
            "'dividida' (ambas direcoes presentes) | 'indeterminado' (n_hits=0 ou "
            "sinal fraco). V1 baseado em regex em excerpt — tuning iterativo "
            "pos-shadow window."
        ),
    )
    n_hits: Optional[int] = Field(
        default=None,
        description="Numero de acordaos retornados pela query (excludente do page>0).",
    )
    top_decisions: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Top 3 ementas: cada item tem process_number, publication_date, excerpt, url. "
            "Use pra citar evidencia na justificativa do risco_jurisprudencial."
        ),
    )
    source: Optional[str] = Field(
        default="provider",
        description="Origem da informacao. V1 sempre 'provider' (jurisprudencias.ai).",
    )
    cached: Optional[bool] = Field(
        default=None,
        description="True quando veio do cache TTL 30d. False quando fresh provider call.",
    )

    model_config = {"extra": "ignore"}


class EvidenceArtifact(BaseModel):
    """Citacao de factsheet/autos que sustenta a sintese L2.

    Substitui o legacy list[dict[str, Any]] que Gemini API rejeitava com
    'additionalProperties is not supported' quando exposto via response_schema.
    """

    mov_id: Optional[str] = Field(
        default=None,
        description="ID do mov_factsheet ou referencia ao day citado.",
    )
    snippet: Optional[str] = Field(
        default=None,
        description="Snippet curto (max ~200 chars) do factsheet/autos que sustenta a sintese.",
    )
    weight: Optional[Literal["high", "medium", "low"]] = Field(
        default=None,
        description="Peso da evidencia.",
    )


class PecaPivoCandidata(BaseModel):
    """Candidata a peca-pivo dentro deste processo (input pro merito_synthesis decidir)."""

    mov_id: Optional[str] = Field(
        default=None,
        description="ID do mov_factsheet com e_pivo=true mais load-bearing. null se nenhum.",
    )
    data: Optional[str] = Field(
        default=None,
        description="YYYY-MM-DD do mov pivo.",
    )
    motivo: Optional[str] = Field(
        default=None,
        description=(
            "1 frase explicando por que esta mov define o estado atual do processo. "
            "Quando varios candidatos: escolha o mais 'load-bearing' "
            "(sentenca > acordao > decisao interlocutoria > peticao)."
        ),
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

    v2.1: APERTADO pra Literal[...] (mesmo motivo de DecisaoVigente).
    """

    classificacao: Optional[Literal[
        "provavel", "possivel", "poucas_chances", "remota",
    ]] = Field(
        default=None,
        description="Classificacao Daycoval. Pesos: provavel=1.0 | possivel=0.7 | poucas_chances=0.4 | remota=0.0001",
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
        description=(
            "1-2 frases PT-BR descrevendo o estado ATUAL do processo. Cite: "
            "(a) instancia atual (1g/2g/etc) e fase (instrucao/sentenca/recurso/execucao/transito); "
            "(b) sentido da decisao vigente; (c) se a garantia esta aceita ou nao."
        ),
    )

    # Campo 2: decisao vigente
    decisao_vigente: DecisaoVigente = Field(default_factory=DecisaoVigente)

    # Campo 3: lifecycle da garantia
    lifecycle_garantia: list[LifecycleGarantiaEvent] = Field(
        default_factory=list,
        description=(
            "Timeline ordenada por data dos eventos de garantia neste processo. "
            "Reconstrua dos factsheets com evento_garantia.tipo != 'nenhum'. "
            "[] se nenhum factsheet menciona apolice."
        ),
    )

    # Campo 4: risco intermediario do processo
    #
    # DEPRECATED PR7.6 (2026-05-31) — comment-only marker, NAO em Field(description)
    # pq description vai pro LLM via response_schema (Gemini) e tag de
    # depreciacao podia ser interpretada como "nao emit" -> silent degradation.
    # Substituido por orthogonal pair (risco_factual + risco_jurisprudencial)
    # na Architecture D. Field mantido backward-compat indefinidamente — drop
    # plan deferido ate L2 schema extendido OU backtest runner migrado pra
    # L3 snapshots (ver ADR-L2-LEGACY-CLEANUP-PR7.6.md secao "Drop ainda nao
    # seguro" + "Decisao revisada PR7.6 Item 4 F1 fix").
    risco_processo_intermediario: Optional[Literal[
        "Baixo", "Medio", "Alto", "Altissimo",
    ]] = Field(
        default="Baixo",
        description=(
            "Risco SO deste processo (NAO o risco do MERITO — esse e camada 3). "
            "Baixo: pendente sem decisao desfavoravel; embargos nao julgados; acordo vigente; "
            "extinto sem merito; suspensao por causa externa (RJ). "
            "Medio: improcedente em 1a inst COM apelacao pendente (efeito suspensivo CPC 1.012), "
            "EXCETO sinais explicitos de irregularidade (penhora, intimacao pagamento). "
            "Alto: sentenca desfavoravel SEM recurso; mantido em 2a inst sem transito. "
            "Altissimo: transito desfavoravel certificado; cumprimento determinado."
        ),
    )

    # Campos 4b/4c: Architecture D — orthogonal risk paths (PR3 shadow).
    # Apenas populated quando flag JURISPRUDENCE_PATH_ENABLED != off + payload
    # tem jurisprudencia_externa (graceful fallback null). L3 PR4 vai aplicar
    # matriz determ pra agregar em `risco_processo_intermediario` (shadow) ou
    # substituir (new). Default None pra ficar bovinamente claro no audit
    # quando flag=off (sem incidente acidental).
    risco_factual: Optional[Literal[
        "Baixo", "Medio", "Alto", "Altissimo", "Indeterminado",
    ]] = Field(
        default=None,
        description=(
            "OBRIGATORIO emitir SEMPRE — escolha um dos 5 valores. Risco derivado "
            "SO do estado processual + Matriz Daycoval (factual). Ignora "
            "jurisprudencia — espelha a logica determinista de tier + "
            "decisao_vigente + lifecycle. Use 'Indeterminado' quando ha realmente "
            "ausencia de sinal factual (cards L1 vazios, sem decisao, sem "
            "lifecycle); NAO emit null."
        ),
    )
    risco_jurisprudencial: Optional[Literal[
        "Baixo", "Medio", "Alto", "Altissimo", "Indeterminado",
    ]] = Field(
        default=None,
        description=(
            "OBRIGATORIO emitir SEMPRE — escolha um dos 5 valores. Risco derivado "
            "SO da jurisprudencia (tese × tribunal). 'Indeterminado' quando n_hits=0 "
            "OR resultado_majoritario indeterminado OR provider indisponivel; NAO "
            "emit null."
        ),
    )

    # Campo 5: trajetoria dentro do processo
    trajetoria_dentro_processo: Optional[Literal[
        "estavel", "deteriorando", "melhorando", "indefinida",
    ]] = Field(
        default="indefinida",
        description=(
            "Sentido da evolucao olhando para a sequencia de delta_risco nos factsheets. "
            "'estavel': sem movs com delta_risco.mudou=true. "
            "'deteriorando': maioria dos deltas aumentou. "
            "'melhorando': maioria dos deltas diminuiu. "
            "'indefinida': misto/insuficiente."
        ),
    )

    # Campo 6: peca-pivo candidata
    peca_pivo_candidata: PecaPivoCandidata = Field(default_factory=PecaPivoCandidata)

    # Campo 7: valores
    valor_em_disputa: Optional[float] = Field(
        default=None,
        description=(
            "Melhor evidencia de valor em disputa (BRL). Use o MAIS RECENTE/MAIOR entre "
            "valor_causa e valor_debito_executado dos factsheets. null se nenhum disponivel."
        ),
    )
    valor_garantia: Optional[float] = Field(
        default=None,
        description=(
            "Valor da apolice/garantia depositada neste processo (BRL). Prefira apolices[].valor_is. "
            "Fallback: valores.valor_garantia dos factsheets. null se nao identificavel."
        ),
    )

    # Campo 8: tipo judicial (determinado upstream por classify_tipo_judicial)
    tipo_judicial: Optional[Literal["fiscal", "trabalhista", "civel"]] = Field(
        default="civel",
        description="Tipo do processo (echo do request). Define qual matriz Daycoval aplicar.",
    )

    # Campo 9: probabilidade de exito (Matriz Daycoval 2026-05-21)
    probabilidade_exito: ProbabilidadeExito = Field(
        default_factory=ProbabilidadeExito,
        description="Probabilidade do tomador ter exito. LLM aplica os criterios objetivos da matriz Daycoval correspondente ao tipo_judicial. Default vazio quando LLM nao retorna (audit no campo classificacao=null).",
    )

    # Meta
    movs_processed: int = Field(default=0, description="Numero de mov_factsheets considerados")
    confianca: float = Field(default=0.7, ge=0.0, le=1.0)
    evidence_artifacts: list[EvidenceArtifact] = Field(
        default_factory=list,
        description=(
            "Lista de 3-5 factsheets que sustentam a sintese. Cada item: "
            "{mov_id, snippet (curto), weight: 'high'|'medium'|'low'}."
        ),
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
    apolices: list[ApoliceContextMin] = Field(default_factory=list)
    # PR7.2 (2026-05-31): tese_jurisprudencia: Optional[TeseJurisprudenciaMin]
    # field REMOVIDO. Provider externo jurisprudencias.ai (jurisprudencia_externa
    # abaixo) eh unica fonte.
    # Architecture D PR3 (2026-05-31): jurisprudencia externa via provider
    # jurisprudencias.ai. Populated quando flag JURISPRUDENCE_PATH_ENABLED != off
    # + merito tem tese_canonica_id + tribunal cabe no provider. None em qualquer
    # outro caso (graceful — prompt L2 nao injeta bloco extra, byte-identical).
    jurisprudencia_externa: Optional[JurisprudenciaExternaMin] = Field(
        default=None,
        description=(
            "Heuristic do provider jurisprudencias.ai pra (tese × tribunal). "
            "Substitui curadoria interna apos shadow window 14d + drop PR5. "
            "null quando flag off OR tese unavailable OR tribunal sem mapping."
        ),
    )
    model: Optional[str] = None
    provider: Optional[str] = None


class ProcessoSynthesisResponse(BaseModel):
    card: ProcessoSynthesisCard
    # dict[str,str] desde split em 2 LLM calls: {"synthesis": ..., "prob_exito": ...}
    raw_response: Optional[dict[str, Any]] = None
    llm_raw_prompt: Optional[dict[str, Any]] = None
    prompt_version: Optional[str] = None
    usage: Optional[dict[str, Any]] = None

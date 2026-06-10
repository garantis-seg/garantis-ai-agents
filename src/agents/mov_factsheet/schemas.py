"""Pydantic schemas pro mov_factsheet agent (engine v6_meritos).

Output rico que substitui o mov_summarizer simples. Cabe em
leads.dossier_artifacts com kind='mov_factsheet'.

Spec canonica do plano: c:/Users/Eltonxp/.claude/plans/risk-engine-v6-meritos.md
"""

from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


# ── Sub-objetos ───────────────────────────────────────────────────────────


class DecisaoBlock(BaseModel):
    """Decisao processual presente na mov."""

    tem_decisao: bool = Field(
        default=False,
        description=(
            "True SO se a mov contem decisao judicial materialmente "
            "(sentenca, acordao, decisao_merito, decisao_interlocutoria, homologacao). "
            "Despachos ordinatorios, publicacoes burocraticas, intimacoes administrativas = false."
        ),
    )
    sentido: Optional[Literal["favoravel", "desfavoravel", "parcial", "neutro"]] = Field(
        default=None,
        description=(
            "Sentido DO PONTO DE VISTA DO TOMADOR (executado/embargante/impetrante). "
            "Em EF: procedente da execucao = desfavoravel; improcedente = favoravel. "
            "Em Embargos/MS/Anulatoria: procedente = favoravel; improcedente = desfavoravel. "
            "Extincao SEM merito SEMPRE 'neutro' (NUNCA desfavoravel) — extincao processual "
            "nao consolida divida nem julga risco. "
            "Se NAO consegue identificar com confianca em qual polo o Tomador esta: "
            "null + confianca<=0.5. NUNCA chute 'Fazenda autora default'."
        ),
    )
    instancia: Optional[Literal["1g", "2g", "stj", "stf"]] = Field(
        default=None,
        description="Instancia do juizo que prolatou a decisao. null se nao identifica.",
    )
    natureza: Optional[Literal[
        "procedente", "improcedente", "parcialmente_procedente",
        "extinto_sem_merito", "homologatoria", "interlocutoria",
    ]] = Field(
        default=None,
        description=(
            "Natureza juridica da decisao. Para movs de RECURSO (provido/nao provido), "
            "prefira deixar null com sentido preenchido — L2 amarra via decisao_vigente. "
            "Use 'interlocutoria' SO se nao houve merito recursal (e.g. nao conhecimento por preliminar)."
        ),
    )
    transito_certificado: bool = Field(
        default=False,
        description="True SO se a mov CERTIFICA transito em julgado (texto explicito).",
    )


class EventoGarantia(BaseModel):
    """Evento envolvendo a garantia/apolice nesta mov."""

    tipo: Literal[
        "apresentacao", "aceitacao", "recusa", "levantamento",
        "substituicao", "reforco", "nenhum",
    ] = Field(
        default="nenhum",
        description=(
            "Tipo de evento envolvendo a garantia. 'nenhum' quando a mov nao trata da garantia. "
            "'apresentacao' quando a parte apresenta apolice/garantia. "
            "'aceitacao'/'recusa' quando o juizo se manifesta sobre a garantia."
        ),
    )
    numero_apolice: Optional[str] = Field(
        default=None,
        description=(
            "Numero da apolice no formato SUSEP (SSSSSAAAAFFFFRRRRNNNNNNN, ~24 digitos) "
            "quando explicito no texto. null se nao houver. NUNCA escreva a palavra 'string'."
        ),
    )
    motivo: Optional[str] = Field(
        default=None,
        description="Quando tipo='recusa': motivo explicito (ex: 'valor insuficiente'). null caso contrario.",
    )


class CDABlock(BaseModel):
    """CDAs/inscricoes em divida ativa mencionadas na mov."""

    numeros: list[str] = Field(
        default_factory=list,
        description="Numeros literais das CDAs mencionadas no texto. [] se nenhuma CDA mencionada.",
    )
    ente: Optional[Literal["estadual", "municipal", "federal_pgfn"]] = Field(
        default=None,
        description="Origem da CDA. null se nao identifica.",
    )
    tributo: Optional[str] = Field(
        default=None,
        description="Sigla do tributo (ICMS, ISS, IPVA, IRPJ, CSLL, etc.). null se nao identifica.",
    )
    valor_total: Optional[float] = Field(
        default=None,
        description="Valor total em BRL quando explicito no texto. null caso contrario.",
    )


class DeltaRisco(BaseModel):
    """Como esta mov alterou o risco do processo/merito vs o estado anterior."""

    mudou: bool = Field(
        default=False,
        description="True se esta mov muda materialmente o risco de acionamento da apolice.",
    )
    direcao: Optional[Literal["aumentou", "diminuiu", "inalterado"]] = Field(
        default=None,
        description=(
            "'aumentou' SO com sinal explicito desfavoravel (sentenca desfavoravel sem suspensivo, "
            "transito desfavoravel, recusa de garantia, intimacao de pagamento). "
            "'diminuiu' com sinal favoravel (acordo, suspensao por RJ, decisao favoravel, transito favoravel). "
            "'inalterado' em atos meramente procedimentais. "
            "ATENCAO: apelacao com efeito suspensivo automatico (CPC art. 1.012) MANTEM inalterado mesmo apos "
            "sentenca de improcedencia."
        ),
    )
    motivo: Optional[str] = Field(
        default=None,
        description="1 frase PT-BR explicando POR QUE mudou (ou nao).",
    )


class ValoresBlock(BaseModel):
    """Valores monetarios extraidos da mov."""

    valor_causa: Optional[float] = Field(
        default=None,
        description="Valor da causa em BRL quando explicito no texto. null caso contrario.",
    )
    valor_debito_executado: Optional[float] = Field(
        default=None,
        description="Valor do debito executado em BRL quando explicito. null caso contrario.",
    )
    valor_garantia: Optional[float] = Field(
        default=None,
        description="Valor da garantia/apolice em BRL quando explicito. null caso contrario.",
    )


class PecaPivo(BaseModel):
    """Indica se esta mov e candidata a peca-pivo do processo/merito."""

    e_pivo: bool = Field(
        default=False,
        description=(
            "True SO se esta mov muda DECISIVAMENTE o estado do merito "
            "(sentenca, acordao, transito em julgado, homologacao de acordo, recusa de garantia). "
            "Despachos, intimacoes, peticoes intermediarias = false."
        ),
    )
    motivo: Optional[str] = Field(
        default=None,
        description="1 frase PT-BR explicando por que esta mov e (ou nao) pivo. null se e_pivo=false e motivo trivial.",
    )


# ── Output card principal ─────────────────────────────────────────────────


class MovFactSheetCard(BaseModel):
    """FactSheet rico de uma movimentacao.

    Cabe em dossier_artifacts.summary com kind='mov_factsheet'.

    Diferente de MovCardSummary (kind='movimentacao'), este card carrega:
    - Estrutura tipada por evento de seguro-garantia (apresentacao/aceitacao/recusa)
    - Delta de risco (sinal explicito de mudanca)
    - Peca-pivo flag (input pra processo_synthesis decidir destaque)
    - Valores monetarios extraidos

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
    resumo_ato: str = Field(
        description=(
            "Resumo PT-BR ACENTUADO do que aconteceu NESTA mov (+ doc anexo + proximo "
            "passo se claro). TAMANHO PROPORCIONAL A RELEVANCIA: ato trivial (guia, "
            "certidao) = 1 frase; decisao/sentenca/evento de garantia = ate ~400 palavras "
            "se houver substancia. O teto e ESPACO, nao meta — nao force nem encha "
            "linguica. NAO copie literalmente do snippet; tecnico-juridico direto. NAO "
            "repita o RESUMO DO PROCESSO nem a MOV ANTERIOR — descreve APENAS esta mov."
        ),
    )
    # tipo_doc: taxonomia v1 (34 valores) — o LLM EMITE este campo (substitui o
    # papel de `categoria` no prompt). `categoria` (14 valores, lida pela L2) é
    # DERIVADA de tipo_doc por código no agent (derivar_categoria), pós-LLM.
    tipo_doc: Literal[
        "sentenca", "acordao", "decisao_interlocutoria", "despacho", "voto",
        "peticao_inicial", "peticao", "contestacao", "recurso", "embargos",
        "contrarrazoes", "certidao", "intimacao", "citacao", "oficio", "mandado",
        "carta_precatoria", "ata_audiencia", "procuracao", "substabelecimento",
        "apolice_seguro_garantia", "fianca_bancaria", "deposito_judicial", "penhora",
        "recusa_aceitacao_garantia", "cda", "guia_recolhimento", "comprovante_pagamento",
        "planilha_calculo", "parecer", "laudo_pericial", "prova_anexa", "ilegivel", "outros",
    ] = Field(
        description="Tipo da peca/documento — UM dos valores da taxonomia v1.",
    )
    relevante_garantia: bool = Field(
        default=False,
        description="true se este ato toca o risco da apolice (garantia/deposito/fianca/caucao/acionamento).",
    )
    # categoria (14 valores canonicos da L2): DERIVADA de tipo_doc no agent
    # (derivar_categoria), NAO emitida pelo LLM. Optional+default=None pra NAO
    # forcar HTTP 500 quando o LLM nao emite (ARMADILHA #1 do blueprint). A L2 le
    # fs.categoria — por isso o agent preenche por codigo antes de instanciar.
    categoria: Optional[Literal[
        "decisao_merito", "decisao_interlocutoria", "sentenca", "acordao",
        "despacho", "peticao", "publicacao", "intimacao", "certidao",
        "ato_ordinatorio", "carga", "baixa", "conclusao", "outros",
    ]] = Field(
        default=None,
        description="DERIVADO de tipo_doc pelo agent (nao emitir). Categoria canonica usada pela L2.",
    )

    # Campo 2: Relevancia pro merito
    relevancia_merito: Literal["alta", "media", "baixa", "ruido"] = Field(
        description=(
            "Quanto este ato influencia a TESE/MERITO do processo principal: "
            "'alta' = decisao de merito, sentenca, acordao, evento de garantia, "
            "intimacao DE PAGAMENTO, transito. "
            "'media' = peticoes recursais, despachos saneadores, atos que viram "
            "o jogo procedural. "
            "'baixa' = despachos ordinatorios, publicacoes burocraticas, atos de cartorio. "
            "'ruido' = cargas, baixas administrativas, intimacoes burocraticas SEM conteudo."
        ),
    )

    # Campo 3: Decisao (sub-objeto)
    decisao: DecisaoBlock = Field(default_factory=DecisaoBlock)

    # Campo 4: Evento de seguro-garantia
    evento_garantia: EventoGarantia = Field(default_factory=EventoGarantia)

    # Campo 5: Status da garantia pos-mov
    status_garantia_pos_mov: Literal[
        "apresentado", "aceito", "recusado", "levantado", "substituido", "nenhum",
    ] = Field(
        default="nenhum",
        description=(
            "Estado da garantia DEPOIS desta mov. Se a mov so APRESENTOU mas nao foi aceita, "
            "status='apresentado' (NAO 'aceito'). 'nenhum' quando a mov nao trata da garantia."
        ),
    )

    # Campo 6: Tipo da garantia
    tipo_garantia: Literal[
        "seguro_garantia", "fianca_bancaria", "carta_fianca",
        "deposito_judicial", "penhora", "fiduciaria", "outras", "nenhum",
    ] = Field(
        default="nenhum",
        description="Tipo da garantia quando mencionada. 'nenhum' se a mov nao trata de garantia.",
    )

    # Campo 7: CDA
    cda: CDABlock = Field(default_factory=CDABlock)

    # Campo 9: Delta de risco
    delta_risco: DeltaRisco = Field(default_factory=DeltaRisco)

    # Campo 10: Valores
    valores: ValoresBlock = Field(default_factory=ValoresBlock)

    # Campo 11: Peca-pivo
    peca_pivo: PecaPivo = Field(default_factory=PecaPivo)

    # Campo 13: Datas/conexos/confianca
    data_real_ato: Optional[str] = Field(
        default=None,
        description=(
            "YYYY-MM-DD do ato real SE DIFERIR da data de publicacao. "
            "Ex: 'sentenca em 10/03/2024 publicada em 15/03/2024' -> data_real_ato='2024-03-10'. "
            "null se a data do ato e igual a data de publicacao."
        ),
    )
    processos_conexos_mencionados: list[str] = Field(
        default_factory=list,
        description="CNJs (formato 7-2.4.1.2.4 ou 20 digitos) mencionados literalmente no texto.",
    )
    confianca: float = Field(
        default=0.7,
        ge=0.0, le=1.0,
        description=(
            "Confianca do LLM nesta classificacao (0-1). "
            "0.9+ se ha doc anexo com decisao clara. "
            "0.7-0.8 se snippet detalhado sem doc. "
            "0.5-0.7 se snippet generico com fallback context. "
            "<0.5 se ruidoso sem nada mais OU se nao identificou polo do Tomador."
        ),
    )


# ── Request / Response ────────────────────────────────────────────────────


class MovInput(BaseModel):
    mov_id: str
    data: Optional[str] = None
    tipo: Optional[str] = None
    texto: str


class ProcessoContext(BaseModel):
    """Contexto minimo do processo pra desambiguar mov isolada.

    FIX CRÍTICO (L1 v7): materia/nm_tomador/cnpj_tomador SÃO enviados pelo shared
    (fetch_processo_context) mas pydantic v2 DESCARTAVA por não serem declarados
    aqui → a fundação (de que lado o Tomador está / grupo econômico) NUNCA chegava
    ao LLM (caso Casas Bahia/Via S.A quebrava). Declarar os 3 campos conserta o
    /classify E a /triage. Ver memory l1-invariante-fundacao."""

    cnj: str
    classe: Optional[str] = None
    classe_cnj_code: Optional[int] = None
    polo_ativo: Optional[str] = None
    polo_passivo: Optional[str] = None
    materia: Optional[str] = None
    nm_tomador: Optional[str] = None
    cnpj_tomador: Optional[str] = None


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
    gcs_url: Optional[str] = Field(
        default=None,
        description=(
            "gs://bucket/path do PDF original. Consumido apenas quando "
            "VISION_L1_ENABLED=true — agent lê PDF e passa pro Gemini Vision "
            "em vez de serializar text_content. Backwards-compatible (None OK)."
        ),
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
    classe: Optional[str] = Field(
        default=None,
        description=(
            "Classe da unidade enviada pelo shared: '1A' (mov sem doc), '1B' (mov+1 doc), "
            "'1C' (mov+N docs), '1D' (documento orfao, sem ato processual). O prompt trata 1D "
            "diferente (doc sem ato). None = trata como mov comum."
        ),
    )
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
    # card: dict (NÃO MovFactSheetCard) — o card já foi validado+dumpado dentro de
    # classify_mov_factsheet (v3.1 = MovFactSheetCard, v4 = MovFactSheetCardV4). Tipá-lo
    # como MovFactSheetCard aqui RE-COERCIA o card v4 de volta pro shape v3.1 (dropava
    # recorrente_polo/provido/… e re-adicionava sentido/cda/confianca). Pass-through.
    card: dict[str, Any]
    raw_response: Optional[str] = None
    llm_raw_prompt: Optional[str] = None
    prompt_version: Optional[str] = None
    usage: Optional[dict[str, Any]] = None

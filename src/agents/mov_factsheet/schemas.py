"""Pydantic schemas de request/response do mov_factsheet agent (engine v6_meritos).

O card que a LLM emite e o `MovFactSheetCardV4` (`schemas_v4.py`).
"""

from typing import Any, Optional
from pydantic import BaseModel, Field


# ── Request / Response ────────────────────────────────────────────────────


class MovInput(BaseModel):
    mov_id: str
    data: Optional[str] = None
    tipo: Optional[str] = None
    texto: str
    # Quantos documentos EXISTEM pra esta mov e NAO passaram no filtro de admissao
    # do loader (sem texto E sem gcs_url). Lido so pela trava de corpo, em
    # `agent.py::_sem_corpo`. >0 significa "ha peca, nao conseguimos
    # ler", que NAO e a mesma coisa que "nao ha peca": no 1o caso o rotulo do
    # provider e ponteiro pra um documento real, e apagar a decisao perderia um fato
    # provavelmente verdadeiro (sub-rating quando adverso).
    # ⛔ Tem de estar DECLARADO aqui: pydantic v2 DESCARTA campo nao declarado em
    # silencio — mesma armadilha que ja custou a fundacao do Tomador (ver o docstring
    # de ProcessoContext logo abaixo).
    docs_inadmissiveis: int = 0


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
    # ⛔ MESMA armadilha do docstring acima: o shared manda `assunto`, e pydantic o
    # DESCARTA se não estiver declarado — o L1 escolheria a família de leitura sem
    # nunca ver o assunto do processo.
    assunto: Optional[str] = None
    # Família já RESOLVIDA pelo shared (garantis_shared.materia). Vem pronta porque
    # o degrau da curadoria lê ref.cnj_classes e este serviço não tem banco
    # (`uses_cloud_sql: false`). Mesmo padrão do `tipo_judicial` do L2.
    familia: Optional[str] = None
    familia_origem: Optional[str] = None


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
            "gs://bucket/path do PDF original. Consumido pelo ramo Vision — "
            "agent lê PDF e passa pro Gemini Vision "
            "em vez de serializar text_content. Backwards-compatible (None OK)."
        ),
    )


class DocGate(BaseModel):
    """1 documento do conjunto, SÓ pro gate de OCR/Vision decidir por documento.

    Existe porque o ramo de petição manda os N documentos da peça CONCATENADOS num
    único `DocAnexado` (a fronteira vai marcada no texto, e o prompt do LLM depende
    desse formato). O gate, porém, decide por PAR (texto do doc i, PDF do doc i):
    com o entry único ele julgaria o texto somado de N docs contra o `gcs_url` de
    UM — no caso que motivou isto (Steel, 2026-08-12), o do AGRAVO, que não contém
    o AIIM procurado. Campo ADITIVO: caller que não manda mantém o comportamento
    antigo (o gate cai nos `documentos_anexados`)."""

    doc_key: Optional[str] = None
    text_content: Optional[str] = None
    gcs_url: Optional[str] = Field(
        default=None, description="gs://bucket/path do PDF deste doc específico",
    )
    so_capa: bool = Field(
        default=False,
        description=(
            "O caller JÁ identificou este documento como a peça que quer (título "
            "literal / código / doctype) e o extrator de texto só alcançou a CAPA. "
            "⇒ o `text_content` NÃO é o documento, e o gate não deve deixar o texto "
            "decidir sozinho. Quem carimba é o `texto_e_so_a_capa` do garantis-shared "
            "(2ª passada da escada afirmativa do `fetch_peticao_doc`). Campo ADITIVO: "
            "default False = comportamento de sempre."
        ),
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
    documentos_gate: list[DocGate] = Field(
        default_factory=list,
        description=(
            "Pares (text_content, gcs_url) POR documento, só pro gate de OCR/Vision. "
            "Mandar quando documentos_anexados vem concatenado (petição). Vazio = "
            "o gate usa documentos_anexados."
        ),
    )
    model: Optional[str] = None
    provider: Optional[str] = None


class MovFactSheetResponse(BaseModel):
    # card: dict — o card já foi validado+dumpado dentro de classify_mov_factsheet
    # (MovFactSheetCardV4, ou o superset PeticaoExtractCardV4 no ramo petição). Tipá-lo
    # aqui RE-COERCERIA o card (o superset perderia cdas/processos_citados). Pass-through.
    card: dict[str, Any]
    raw_response: Optional[str] = None
    llm_raw_prompt: Optional[str] = None
    prompt_version: Optional[str] = None
    usage: Optional[dict[str, Any]] = None
    vision_gate: Optional[dict[str, Any]] = Field(
        default=None,
        description=(
            "Veredito do gate de OCR/Vision: {n_docs, n_inalcancaveis, n_enviados, "
            "motivo}. O caller persiste — zero bloqueado + zero enviado é gate MUDO, "
            "não gate ocioso."
        ),
    )

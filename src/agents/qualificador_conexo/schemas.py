"""Contrato do `POST /ficha/qualificar-conexo` (S2c, card 869ffv22t).

Molde "determinismo máximo" do plano de 21/10/2026 (Parte 1.2):

1. Entrada mínima. O chamador manda só o que as 2 perguntas exigem.
2. Alertas do código. O chamador manda `alertas[]`. O LLM responde cada um.
3. Schema fechado. Todo modelo usa `extra="forbid"`. Enum onde cabe.
   Campo livre só com teto de caracteres.

Há 3 grupos de modelos:

- Entrada (`QualificarConexoRequest`): o que o chamador manda.
- Emissão do LLM (`QualificacaoLLM`): o que o LLM devolve na fase B. O código
  valida este objeto com as regras duras (`agent.validar_qualificacao`).
- Saída (`QualificarConexoResponse`): a emissão do LLM mais os campos que o
  CÓDIGO calcula (`fonte`, `requer_revisao`, `divergencias`, custo, modelo).
  O LLM não escreve estes campos.
"""
from __future__ import annotations

from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

#: Tetos de texto livre (pedido de 22/10/2026).
MAX_TRECHO = 300
MAX_MOTIVO = 200

EspecieGarantia = Literal[
    "surety_bond", "bank_letter_of_guarantee", "judicial_deposit", "judicial_attachment",
]
EstadoGarantia = Literal["ativa", "substituida", "liberada", "sem_evidencia"]
Confianca = Literal["alta", "media", "baixa"]
Fonte = Literal["documentos", "capa"]
RespostaAlerta = Literal["confirmado", "refutado"]
EscopoAlerta = Literal["processo", "garantia", "conexo"]


class _Fechado(BaseModel):
    """Base de todo modelo deste contrato: chave extra é erro."""

    model_config = ConfigDict(extra="forbid")


# ── Entrada ─────────────────────────────────────────────────────────────────


class Empresa(_Fechado):
    razao_social: str
    cnpj_raiz: str
    grupo_economico: list[str] = Field(
        default_factory=list, description="Raízes de CNPJ do grupo econômico",
    )


class ProcessoEntrada(_Fechado):
    numero: str
    item_type: str
    classe_cnj_code: Optional[Union[int, str]] = None
    assunto: Optional[str] = None
    tribunal: Optional[str] = None
    partes: Optional[list[str]] = None
    e_da_empresa: bool


class GarantiaEntrada(_Fechado):
    """`id` é o de `garantis_shared.fichas.contratos.garantia_id`.

    A S2c, o fe-api e a S2 usam a mesma função para o id. Assim, as 3 etapas
    falam da mesma garantia.
    """

    id: str
    especie: EspecieGarantia
    issuer_code: Optional[str] = None
    valor: Optional[float] = None
    susep_number: Optional[str] = None
    termination_date: Optional[str] = None
    processo_numero: Optional[str] = None


class DocumentoDoIndice(_Fechado):
    """Um item do índice da S2b.

    Os campos de metadado vêm de `garantis_shared.fichas.indice_docs` (o ItemDoc).
    O `documento_indexado` é o `to_dict()` do `DocumentoIndexado` que o
    `/doc-indexer/indexar` devolve. Sem ele, o agente vê o documento no índice
    mas não consegue ler o documento.
    """

    doc_id: str
    nome: Optional[str] = None
    tipo: Optional[str] = None
    paginas: Optional[int] = Field(default=None, description="Número de páginas")
    ancora: Optional[Union[str, dict[str, Any]]] = None
    gcs_path: Optional[str] = None
    processo_numero: Optional[str] = None
    data: Optional[str] = None
    movimento_ref: Optional[str] = None
    grau: Optional[str] = None
    fls: Optional[str] = None
    documento_indexado: Optional[dict[str, Any]] = None


class AlertaEntrada(_Fechado):
    """Um alerta que o CÓDIGO detectou. O LLM tem de confirmar ou refutar."""

    codigo: str = Field(max_length=80)
    escopo: EscopoAlerta
    alvo: str
    texto: str = Field(max_length=500)


class QualificarConexoRequest(_Fechado):
    conexo_id: Union[int, str]
    empresa: Empresa
    classe_macro: Literal["FISCAL"]
    processos: list[ProcessoEntrada] = Field(min_length=1)
    garantias: list[GarantiaEntrada] = Field(default_factory=list)
    documentos_indexados: list[DocumentoDoIndice] = Field(default_factory=list)
    alertas: list[AlertaEntrada] = Field(default_factory=list)
    auditar: bool = Field(
        default=True, description="Liga o auditor (segundo modelo, família diferente)",
    )


# ── Emissão do LLM (fase B) ─────────────────────────────────────────────────


class Prova(_Fechado):
    doc_id: str
    pagina: int = Field(ge=1)
    trecho: str = Field(min_length=1, max_length=MAX_TRECHO)


class DebitoCoberto(_Fechado):
    processo_numero: str
    valor: Optional[float] = None


class ProcessoLLM(_Fechado):
    numero: str
    e_fiscal: bool
    confianca: Confianca
    prova: Optional[Prova] = None
    motivo: str = Field(min_length=1, max_length=MAX_MOTIVO)


class GarantiaLLM(_Fechado):
    id: str
    estado: EstadoGarantia
    substituida_por: Optional[str] = None
    debito_coberto: Optional[DebitoCoberto] = None
    prova: Optional[Prova] = None
    documentos_lidos: list[str] = Field(default_factory=list)
    confianca: Confianca = "media"
    motivo: str = Field(default="", max_length=MAX_MOTIVO)


class AlertaRespondidoLLM(_Fechado):
    codigo: str
    alvo: str
    resposta: RespostaAlerta
    prova: Optional[Prova] = None
    motivo: str = Field(min_length=1, max_length=MAX_MOTIVO)


class QualificacaoLLM(_Fechado):
    processos: list[ProcessoLLM]
    garantias: list[GarantiaLLM] = Field(default_factory=list)
    alertas_respondidos: list[AlertaRespondidoLLM] = Field(default_factory=list)


# ── Saída ───────────────────────────────────────────────────────────────────


class ProcessoQualificado(ProcessoLLM):
    fonte: Fonte
    requer_revisao: bool = False


class GarantiaQualificada(GarantiaLLM):
    fonte: Fonte
    requer_revisao: bool = False


class AlertaRespondido(AlertaRespondidoLLM):
    requer_revisao: bool = False


class Divergencia(_Fechado):
    """Uma afirmação que o auditor não aceitou."""

    alvo_tipo: Literal["processo", "garantia", "alerta"]
    alvo: str
    codigo: Optional[str] = None
    afirmacao: str
    motivo: str = Field(max_length=MAX_MOTIVO)


class ErroCampo(_Fechado):
    """Erro estruturado da validação: o que volta ao LLM e ao chamador."""

    campo: str
    erro: str
    valor_anterior: Any = None


class QualificarConexoResponse(_Fechado):
    conexo_id: Union[int, str]
    processos: list[ProcessoQualificado]
    garantias: list[GarantiaQualificada]
    alertas_respondidos: list[AlertaRespondido]
    divergencias: list[Divergencia] = Field(default_factory=list)
    requer_revisao: bool = False
    modo: Literal["documentos", "capa"]
    auditado: bool = False
    budget_esgotado: bool = False
    rodadas_de_correcao: int = 0
    custo_usd: float = 0.0
    chamadas: int = Field(default=0, description="Chamadas de ferramenta na fase A")
    chamadas_llm: int = Field(default=0, description="Chamadas de LLM de todas as fases")
    modelo: str
    modelo_auditor: Optional[str] = None
    prompt_version: str


class QualificacaoInvalidaBody(_Fechado):
    """Corpo do HTTP 422 quando a emissão falha nas regras duras."""

    erro: Literal["qualificacao_invalida"] = "qualificacao_invalida"
    erros: list[ErroCampo]
    rodadas: int
    custo_usd: float
    modelo: str
    prompt_version: str


__all__ = [
    "MAX_MOTIVO",
    "MAX_TRECHO",
    "AlertaEntrada",
    "AlertaRespondido",
    "AlertaRespondidoLLM",
    "DebitoCoberto",
    "Divergencia",
    "DocumentoDoIndice",
    "Empresa",
    "ErroCampo",
    "GarantiaEntrada",
    "GarantiaLLM",
    "GarantiaQualificada",
    "ProcessoEntrada",
    "ProcessoLLM",
    "ProcessoQualificado",
    "Prova",
    "QualificacaoInvalidaBody",
    "QualificacaoLLM",
    "QualificarConexoRequest",
    "QualificarConexoResponse",
]

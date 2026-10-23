"""Schemas Pydantic do ficha_writer (S4, redação dos slots de texto da ficha).

O contrato de wire tem 3 modos. O modo sai do request:

- **v5** (`nucleo` e `indice_navegavel` presentes, 23/10/2026): o v4 mais a leitura
  dos autos. O núcleo entra inteiro no prompt. O agente abre os documentos do índice
  com ferramentas. A saída leva `trilha_leitura[]`. Ver `agent_v5.py`.

- **v4** (`esqueleto` presente): o request leva o tipo, o trilho, o esqueleto
  determinístico (fatos fixos), os alertas do código, as lições e os processos que o
  texto pode citar. A saída leva `alertas_respondidos[]`. O agente valida a saída e
  corrige em até 3 rodadas internas.
- **v3** (`esqueleto` ausente): o comportamento antigo, sem mudança. Ele fica até o
  shared ligar o v4 no `fichas/redator.py` (card 869ffv22t). Depois desse PR do
  shared, um PR remove o v3. Decisão de 22/10/2026.

Os slots são ACHATADOS: cada slot é uma string ("bullets[0]", "merito.p1", ...).

Decisão de 22/10/2026: todo modelo de ENTRADA usa `extra="forbid"`. Uma chave
desconhecida dá 422. Antes, `extra="ignore"` descartava o `tipo_ficha` em silêncio
(defeito 7 do plano de 21/10/2026). A exceção é o `esqueleto`: ele é a ficha
determinística inteira, e um bloco novo do esqueleto (fiança, renovação) tem de chegar
ao prompt como fato fixo sem um deploy coordenado.
"""

from __future__ import annotations

from typing import Any, Literal, Optional, Union

from pydantic import AliasChoices, BaseModel, Field, model_validator

# Os 7 tipos do shared (`garantis_shared.fichas.contratos.TIPOS_FICHA`).
TipoFicha = Literal[
    "nova_apolice",
    "renovacao_interna",
    "renovacao_congenere",
    "substituicao_deposito",
    "substituicao_fianca",
    "substituicao_penhora",
    "indefinido",
]

# Os 4 trilhos da S3b e da S5 (`validadores.apendice_a.TRILHOS`).
Trilho = Literal["carf", "estadual", "ef", "acoes_contribuinte"]

# A chave do Livro: as chaves de `livro_guidance.json` (tipos).
TipoLivro = Literal[
    "nova_apolice@carf",
    "nova_apolice@estadual",
    "nova_apolice@ef",
    "nova_apolice@acoes_contribuinte",
    "substituicao_fianca",
    "substituicao_deposito",
    "substituicao_penhora",
    "renovacao_congenere",
    "renovacao_interna",
]

_FORBID = {"extra": "forbid"}


class CampoSpec(BaseModel):
    """Spec de UM slot de texto.

    `max` é o limite DURO de caracteres. O layout do PDF quebra se o texto estourar.
    No v4 o agente confere o `max` na saída. No v3 só o prompt cita o limite.

    `guidance`, `exemplos` e `proibicoes` vazios: no v4 o agente usa os do Livro
    (`livro_guidance.json`). `obrigatorio` ausente: o agente usa o do Livro (o default
    é True, menos `observacao` e os bullets opcionais do tipo).
    """

    nome: str = Field(description="Chave do slot na resposta (ex.: 'bullets[2]', 'merito.p1').")
    path: str = Field(default="", description="Path informativo do slot na FichaJSON.")
    max: int = Field(gt=0, description="Limite DURO de caracteres do slot.")
    obrigatorio: Optional[bool] = Field(
        default=None, description="Slot vazio reprova. Ausente = o valor do Livro.")
    guidance: str = Field(default="", description="Instrução de conteúdo e tom do slot.")
    exemplos: list[str] = Field(default_factory=list, description="Exemplos bons (few-shot).")
    proibicoes: list[str] = Field(
        default_factory=list, description="Frases e assuntos que o slot não pode ter.")

    model_config = _FORBID


class CampoComErro(BaseModel):
    """Um slot que reprovou e volta para o retry.

    Aceita `nome` (contrato do shared hoje) ou `campo` (o formato que o v4 devolve em
    `erros[]`). Assim o shared reenvia `erros[]` sem traduzir.
    """

    nome: str = Field(
        validation_alias=AliasChoices("nome", "campo"),
        description="Nome do slot com erro (casa com uma CampoSpec).",
    )
    erro: str = Field(description="O erro (ex.: 'bullets[2] > 150 chars').")
    valor_anterior: Any = Field(default=None, description="O texto que reprovou.")

    model_config = _FORBID


class Alerta(BaseModel):
    """Um fato que o CÓDIGO detectou antes do LLM. O LLM responde cada um."""

    codigo: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_.:-]+$")
    texto: str = Field(min_length=1, max_length=600)

    model_config = _FORBID


class EtapaEsqueleto(BaseModel):
    etapa: str
    status: str
    subtitulo: Optional[str] = ""

    model_config = {"extra": "allow"}


class ValorEsqueleto(BaseModel):
    """O valor que a S3 decidiu. `garantia` null = valor desconhecido (caderno, itens 3–4)."""

    garantia: Optional[Union[float, str]] = None
    garantia_fmt: Optional[str] = None
    grau: Optional[str] = None
    origem: Optional[str] = None
    label: Optional[str] = None

    model_config = {"extra": "allow"}


class Esqueleto(BaseModel):
    """A ficha determinística (S3b). Cada campo aqui é FATO FIXO para o texto.

    `extra="allow"` de propósito (ver o docstring do módulo). Os slots de texto e a
    `metadata` que vierem aqui NÃO entram no prompt como fato (ver
    `prompts._fatos_fixos`).
    """

    empresa: str = Field(min_length=1)
    cnpj: str = Field(min_length=1)
    processo_id: str = Field(min_length=1)
    pipeline: list[EtapaEsqueleto] = Field(default_factory=list)
    etapa_atual: Optional[str] = None
    valor: ValorEsqueleto
    termometro: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    divida_ativa: Optional[dict[str, Any]] = None
    ultima_decisao: Optional[dict[str, Any]] = None
    processo_judicial: Optional[dict[str, Any]] = None

    model_config = {"extra": "allow"}


# ── v5: o núcleo obrigatório, o índice navegável e a trilha de leitura ────────
#
# Decisão do Alfredo de 23/10/2026: "núcleo obrigatório + índice navegável". O
# núcleo entra INTEIRO no prompt: é a leitura obrigatória. O índice diz o que mais
# existe nos autos. O agente abre um documento do índice com as ferramentas do
# investigador. O auditor v3 (`auditor_ficha`) usa os MESMOS modelos.

#: Teto do `trecho_apoio` da trilha (pedido de 23/10/2026).
MAX_TRECHO_APOIO = 200


class DocNucleo(BaseModel):
    """Um documento do núcleo: o texto inteiro já vem no request."""

    doc_id: str = Field(min_length=1)
    texto: str = Field(min_length=1)

    model_config = _FORBID


class AcordaoNucleo(DocNucleo):
    """Um acórdão do núcleo. `processo` é o número do processo do acórdão."""

    processo: Optional[str] = None


class Nucleo(BaseModel):
    """A leitura obrigatória do redator v5 e do auditor v3.

    `cdas`, `premissas_v3` e `qualificacao_s2c` são dados do shared. Eles entram no
    prompt como vieram (JSON), dentro da cerca.
    """

    acordaos: list[AcordaoNucleo] = Field(default_factory=list)
    peticao_inicial: Optional[DocNucleo] = None
    ultima_decisao: Optional[DocNucleo] = None
    cdas: list[Any] = Field(default_factory=list)
    premissas_v3: Optional[Any] = None
    qualificacao_s2c: Optional[Any] = None

    model_config = _FORBID

    def documentos(self) -> list[DocNucleo]:
        """Os documentos com texto do núcleo, na ordem: acórdãos, petição, decisão."""
        docs: list[DocNucleo] = list(self.acordaos)
        docs += [d for d in (self.peticao_inicial, self.ultima_decisao) if d is not None]
        return docs


class ItemIndice(BaseModel):
    """Um documento do índice navegável (o que mais existe nos autos).

    `documento_indexado` é o `to_dict()` do `DocumentoIndexado` do doc_indexer. Sem
    ele, o agente vê o documento no índice, mas não consegue abrir o documento.
    """

    doc_id: str = Field(min_length=1)
    nome: Optional[str] = None
    tipo: Optional[str] = None
    data: Optional[str] = None
    processo: Optional[str] = None
    paginas: Optional[int] = Field(default=None, ge=0)
    n_chars: Optional[int] = Field(default=None, ge=0)
    documento_indexado: Optional[dict[str, Any]] = None

    model_config = _FORBID


class TrilhaItem(BaseModel):
    """O que o redator leu para escrever um slot.

    `paginas` vazia vale para documento do núcleo (texto sem página).
    """

    slot: str = Field(min_length=1)
    doc_id: str = Field(min_length=1)
    paginas: list[int] = Field(default_factory=list)
    trecho_apoio: str = Field(min_length=1, max_length=MAX_TRECHO_APOIO)

    model_config = _FORBID


class FichaWriteFieldsRequest(BaseModel):
    """Request do POST /ficha/write-fields."""

    dossie: Union[dict[str, Any], str] = Field(
        description="Os fatos. No v4, texto ou dict já filtrado pelo shared.")
    campos: list[CampoSpec] = Field(description="Specs dos slots de texto.")
    campos_com_erro: Optional[list[CampoComErro]] = Field(
        default=None, description="Retry: gerar SÓ estes slots e responder SÓ com eles.")
    tipo_ficha: Optional[TipoFicha] = Field(default=None, description="Tipo da S2.")
    tipo_livro: Optional[TipoLivro] = Field(
        default=None, description="Chave do Livro. Ausente = derivada de tipo_ficha + trilho.")
    trilho: Optional[Trilho] = Field(default=None, description="Trilho da S3b.")
    esqueleto: Optional[Esqueleto] = Field(
        default=None, description="A ficha determinística. Presente = modo v4.")
    alertas: list[Alerta] = Field(default_factory=list, description="Alertas do código.")
    licoes: list[str] = Field(default_factory=list, description="Lições vivas da etapa.")
    processos_citaveis: Optional[list[str]] = Field(
        default=None,
        description=(
            "Números de processo que o texto pode citar, além dos do esqueleto. Outro "
            "número de processo no texto reprova (regra de 28/09/2026)."
        ),
    )
    nucleo: Optional[Nucleo] = Field(
        default=None, description="v5: a leitura obrigatória. Com `indice_navegavel` = v5.")
    indice_navegavel: Optional[list[ItemIndice]] = Field(
        default=None, description="v5: o que mais existe nos autos. Com `nucleo` = v5.")
    provider: Optional[str] = Field(default=None, description="LLM provider override.")
    model: Optional[str] = Field(default=None, description="Model override.")

    model_config = _FORBID

    @property
    def modo_v4(self) -> bool:
        return self.esqueleto is not None

    @property
    def modo_v5(self) -> bool:
        return self.nucleo is not None and self.indice_navegavel is not None

    @model_validator(mode="after")
    def _contrato_v4(self) -> "FichaWriteFieldsRequest":
        codigos = [a.codigo for a in self.alertas]
        if len(codigos) != len(set(codigos)):
            raise ValueError("alertas: código repetido")
        # 23/10/2026 (DECIDI-SOZINHO, classe A): meio v5 é contrato quebrado. Cair no
        # v4 em silêncio jogaria fora a leitura que o shared mandou.
        if (self.nucleo is None) != (self.indice_navegavel is None):
            raise ValueError("v5 exige `nucleo` e `indice_navegavel` juntos")
        if self.modo_v5:
            if self.esqueleto is None:
                raise ValueError("v5 (nucleo + indice_navegavel) exige esqueleto")
            ids = [d.doc_id for d in self.indice_navegavel or []]
            if len(ids) != len(set(ids)):
                raise ValueError("indice_navegavel: doc_id repetido")
        if not self.modo_v4:
            return self
        if self.tipo_ficha is None:
            raise ValueError("v4 (esqueleto presente) exige tipo_ficha")
        if self.tipo_ficha == "indefinido":
            raise ValueError("tipo_ficha 'indefinido' não tem redação: a S0 bloqueia antes da S4")
        if self.tipo_ficha == "nova_apolice" and self.tipo_livro is None and self.trilho is None:
            raise ValueError("nova_apolice exige trilho (ou tipo_livro) para achar o Livro")
        if self.tipo_livro is not None and not self.tipo_livro.startswith(self.tipo_ficha):
            raise ValueError(
                f"tipo_livro {self.tipo_livro!r} não é do tipo_ficha {self.tipo_ficha!r}")
        return self


class AlertaRespondido(BaseModel):
    """A resposta do LLM a um alerta do código."""

    codigo: str
    resposta: Literal["acatado", "refutado"]
    motivo: str


class ErroDeCampo(BaseModel):
    """Um erro da validação do v4, no formato do retry."""

    campo: str
    erro: str
    valor_anterior: Any = None


class FichaWriteFieldsResponse(BaseModel):
    """Response do POST /ficha/write-fields.

    v3: `campos` traz exatamente os nomes pedidos. Em falha, `success=false`,
    `campos={}` e `error`.

    v4: `campos` traz os slots aprovados. `alertas_respondidos` traz uma resposta por
    alerta. Em falha depois de 3 rodadas, `success=false`, `erros[]` no formato
    `{campo, erro, valor_anterior}` e `campos` com o que já passou (o caller não
    injeta nada quando `success=false`).
    """

    success: bool
    campos: dict[str, str] = Field(default_factory=dict)
    model: str = ""
    cost_usd: float = 0.0
    error: Optional[str] = None
    prompt_version: str = ""
    tipo_livro: Optional[str] = None
    alertas_respondidos: list[AlertaRespondido] = Field(default_factory=list)
    erros: list[ErroDeCampo] = Field(default_factory=list)
    rodadas: int = 0
    campos_nao_aplicaveis: list[str] = Field(default_factory=list)
    #: slot -> motivo, para cada nome de `campos_nao_aplicaveis` (23/10/2026).
    motivos_nao_aplicaveis: dict[str, str] = Field(default_factory=dict)
    #: Avisos do código que não reprovam (ex.: `renovacao_sem_bloco`, 23/10/2026).
    avisos: list[str] = Field(default_factory=list)
    #: v5 (23/10/2026): a trilha dos slots aprovados. O auditor v3 recebe esta lista.
    trilha_leitura: list[TrilhaItem] = Field(default_factory=list)
    #: v5: os doc_id do índice que a fase A abriu com sucesso.
    documentos_lidos: list[str] = Field(default_factory=list)
    #: v5: chamadas de ferramenta da fase A e o estado do budget.
    chamadas_ferramenta: int = 0
    budget_esgotado: bool = False

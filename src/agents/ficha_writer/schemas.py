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

Decisão de 23/10/2026 (422 da rodada IRB 1481420): o `nucleo` e o item do
`indice_navegavel` também são exceção. Eles seguem a forma do shared
(`garantis_shared.fichas.v2`). Uma chave desconhecida dentro deles vira log
(`FICHA_NUCLEO_CHAVE_IGNORADA`), não 422. O topo do request continua fechado.
"""

from __future__ import annotations

import logging
from typing import Any, Literal, Optional, Union

from pydantic import AliasChoices, BaseModel, Field, model_validator

logger = logging.getLogger(__name__)

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


# ── Contrato do núcleo: a forma que o shared manda (23/10/2026) ───────────────
#
# Defeito de 23/10/2026 (rodada real, IRB 1481420): o shared 1.826.0 mandou o
# núcleo de `garantis_shared.fichas.v2.montar_nucleo`, e o redator v5 respondeu
# HTTP 422 (`nucleo.cdas` não era lista, `nucleo.metadados` era chave extra). Dois
# agentes construíram os 2 lados em paralelo, e os lados divergiram. O contrato que
# vale é o do shared, que produz o dado.
#
# Regra (23/10/2026): o topo do request continua `extra="forbid"`. Dentro do núcleo
# e no item do índice, uma chave desconhecida NÃO dá 422: o schema ignora a chave e
# registra um log `FICHA_NUCLEO_CHAVE_IGNORADA`. O núcleo é dado do shared. Uma chave
# nova do shared não pode derrubar a redação sem um deploy coordenado.
# A forma real fica em `tests/fixtures/nucleo_shared_1826.json` (teste de contrato).


def _chaves_aceitas(modelo: type[BaseModel]) -> set[str]:
    """O nome e os aliases de cada campo do modelo."""
    chaves: set[str] = set()
    for nome, campo in modelo.model_fields.items():
        chaves.add(nome)
        alias = campo.validation_alias
        if isinstance(alias, AliasChoices):
            chaves.update(c for c in alias.choices if isinstance(c, str))
        elif isinstance(alias, str):
            chaves.add(alias)
    return chaves


class _DadoDoShared(BaseModel):
    """Modelo de dado do shared: chave desconhecida vira log, não 422."""

    model_config = {"extra": "ignore", "populate_by_name": True}

    @model_validator(mode="before")
    @classmethod
    def _logar_chave_desconhecida(cls, data: Any) -> Any:
        if isinstance(data, dict):
            fora = sorted(set(data) - _chaves_aceitas(cls))
            if fora:
                logger.warning("FICHA_NUCLEO_CHAVE_IGNORADA modelo=%s chaves=%s",
                               cls.__name__, fora)
        return data


class DocNucleo(_DadoDoShared):
    """Um documento do núcleo: o texto inteiro já vem no request.

    A forma do shared (`montar_nucleo`) é `{doc_id, nome, tipo, data, processo, papel,
    movimento_ref, texto_completo, n_chars, marca, fonte}`. O texto chega em
    `texto_completo` (shared) ou em `texto` (forma antiga). O texto pode vir vazio
    quando o documento é imagem (`marca = "sem_texto_imagem"`).
    """

    doc_id: str = Field(min_length=1)
    texto: str = Field(default="", validation_alias=AliasChoices("texto_completo", "texto"))
    nome: Optional[str] = None
    tipo: Optional[str] = None
    data: Optional[str] = None
    processo: Optional[str] = None
    papel: Optional[str] = None
    movimento_ref: Optional[str] = None
    n_chars: Optional[int] = Field(default=None, ge=0)
    marca: Optional[str] = None
    fonte: Optional[str] = None


class AcordaoNucleo(DocNucleo):
    """Forma antiga: um acórdão do núcleo. `processo` é o número do processo."""


class CdasNucleo(_DadoDoShared):
    """As CDAs do núcleo, na forma do shared (`v2._cdas_do_payload`).

    `divida_ativa` é o bloco do esqueleto. `inscricoes_membros` são os membros do
    conexo do tipo inscrição. `valor_cdas` é a soma em reais.
    """

    divida_ativa: Optional[dict[str, Any]] = None
    inscricoes_membros: list[dict[str, Any]] = Field(default_factory=list)
    valor_cdas: Optional[float] = None
    da_verificada_em: Optional[str] = None


class Nucleo(_DadoDoShared):
    """A leitura obrigatória do redator v5 e do auditor v3.

    A forma do shared 1.826 (`v2.montar_nucleo`) é `{metadados, cdas, premissas_v3,
    qualificacao, documentos}`. O schema também aceita a forma antiga: `acordaos`,
    `peticao_inicial` e `ultima_decisao` separados, `cdas` como lista e
    `qualificacao_s2c` no lugar de `qualificacao`.
    """

    metadados: Optional[dict[str, Any]] = None
    #: A chave do shared é `documentos`. O campo tem outro nome porque `documentos()`
    #: é o método que o redator e o auditor chamam.
    docs: list[DocNucleo] = Field(
        default_factory=list, validation_alias=AliasChoices("documentos", "docs"),
        serialization_alias="documentos")
    acordaos: list[AcordaoNucleo] = Field(default_factory=list)
    peticao_inicial: Optional[DocNucleo] = None
    ultima_decisao: Optional[DocNucleo] = None
    cdas: Union[CdasNucleo, list[Any], None] = None
    premissas_v3: Optional[Any] = None
    qualificacao: Optional[Any] = Field(
        default=None, validation_alias=AliasChoices("qualificacao", "qualificacao_s2c"))

    def documentos(self) -> list[DocNucleo]:
        """Todo documento do núcleo, na ordem: `documentos`, acórdãos, petição, decisão."""
        docs: list[DocNucleo] = list(self.docs) + list(self.acordaos)
        docs += [d for d in (self.peticao_inicial, self.ultima_decisao) if d is not None]
        return docs


class ItemIndice(_DadoDoShared):
    """Um documento do índice navegável (o que mais existe nos autos).

    A forma do shared é `v2.indice_navegavel`: o `DocumentoDoIndice` do qualificador
    do conexo mais `processo`, `n_chars` e `marca`. `documento_indexado` é o
    `to_dict()` do `DocumentoIndexado` do doc_indexer. Sem ele, o agente vê o
    documento no índice, mas não consegue abrir o documento.
    """

    doc_id: str = Field(min_length=1)
    nome: Optional[str] = None
    tipo: Optional[str] = None
    data: Optional[str] = None
    processo: Optional[str] = None
    processo_numero: Optional[str] = None
    paginas: Optional[int] = Field(default=None, ge=0)
    n_chars: Optional[int] = Field(default=None, ge=0)
    marca: Optional[str] = None
    ancora: Optional[Union[str, dict[str, Any]]] = None
    gcs_path: Optional[str] = None
    movimento_ref: Optional[str] = None
    grau: Optional[str] = None
    fls: Optional[str] = None
    documento_indexado: Optional[dict[str, Any]] = None


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


class RodadaDetalhe(BaseModel):
    """Uma rodada da fase B do v5 (24/10/2026).

    O `S4.json` só trazia o nº de rodadas e os erros da última. Um fato sem fonte que
    uma rodada corrigiu não deixava rastro. O debugger visual lê esta lista.
    """

    rodada: int
    #: Os erros da rodada. A rodada aprovada tem `erros=[]`.
    erros: list[ErroDeCampo] = Field(default_factory=list)
    #: Os slots que o prompt da rodada pediu.
    slots_pedidos: list[str] = Field(default_factory=list)
    #: Os slots pedidos que a saída do LLM trouxe em `campos`.
    slots_devolvidos: list[str] = Field(default_factory=list)
    #: Os documentos que o código abriu na rodada para conferir uma trilha. A fase B
    #: não tem ferramenta do LLM. As chamadas da fase A ficam no topo da resposta.
    chamadas_ferramenta: int = 0
    #: Os avisos novos do código na rodada (ex.: `trecho_aproximado`).
    avisos: list[str] = Field(default_factory=list)


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
    #: v5 (24/10/2026): uma entrada por rodada da fase B, inclusive a aprovada.
    rodadas_detalhe: list[RodadaDetalhe] = Field(default_factory=list)
    #: O redator que respondeu: "ficha_writer_v5" ou "ficha_writer_v4". O v3 omite.
    versao: Optional[str] = None
    #: O modo do request: "v5" ou "v4". O v3 omite (24/10/2026).
    modo: Optional[str] = None

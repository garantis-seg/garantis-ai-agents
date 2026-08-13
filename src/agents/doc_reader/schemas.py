"""Contrato de wire do `/doc-reader/perguntar` e do `/doc-reader/resumir`.

Envelope da casa (`{success, …, model, cost_usd}`): falha de parse ou de
validação devolve `success=false` com **HTTP 200** — quem decide o que fazer é o
Investigador, que transforma isso em rejeição de rodada e itera com contexto.
500 fica só para falha inesperada de infra, como `calculo_ficha.py` documenta.

O `documento_indexado` entra como `dict` puro (o `to_dict()` do shared), não como
modelo Pydantic espelhado — mesma decisão do `doc_indexer` (onda 2) e pelo mesmo
motivo: o contrato do `DocumentoIndexado` mora em **um** lugar
(`garantis_shared.calculo_fichas.documento`), e um espelho aqui seria uma segunda
definição que divergiria no primeiro campo novo.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class PerguntarRequest(BaseModel):
    """`{doc_id, doc_hash, pergunta, documento_indexado, n_dinco?}`.

    `doc_hash` é **obrigatório** e é conferido contra o documento carregado. O
    indexador da onda 2 aceita o hash como opcional porque lá ele é o ponteiro
    congelado do `/start` e pode legitimamente não ter sido calculado ainda;
    aqui o documento **já** foi indexado, então o hash existe sempre e não
    exigi-lo abriria a porta para ler outro documento em silêncio — o modo de
    falha caro que o §1.6 nomeia.

    `documento_indexado` inline é a fonte do documento nesta onda. A onda 2
    **não persiste**: o `doc_indexer` devolve o `DocumentoIndexado` na resposta
    HTTP e declara `cache_hit: false` porque a camada de cache é a onda 3
    (`journal.py`, ainda fora da wheel). Inventar aqui um store GCS que o
    indexador não escreve seria fabricar uma fonte de verdade que ninguém
    alimenta. Quando a onda 3 entrar, o campo vira opcional e a rota busca por
    `(doc_hash, extractor_version)` — o shape do envelope não muda.
    """

    doc_id: str = Field(description="Identidade do ItemDoc (#347) — a MESMA das duas fases")
    doc_hash: str = Field(description="sha256 do PDF; conferido contra o documento carregado")
    pergunta: str = Field(description="A pergunta pontual do Investigador")
    documento_indexado: dict[str, Any] = Field(
        description="O `to_dict()` do DocumentoIndexado (saída do /doc-indexer/indexar)"
    )
    n_dinco: Optional[int] = Field(
        default=None,
        description="N do self-consistency (§5.2). Viaja no envelope; N=1 efetivo nesta onda",
    )
    provider: Optional[str] = Field(default=None, description="Override do provider LLM")
    model: Optional[str] = Field(default=None, description="Override do modelo")


class PerguntarResponse(BaseModel):
    """`{success, resposta, citacoes, confianca, objeto_da_confianca, …}`.

    `encontrou=False` com `lacuna` preenchida é **sucesso**, não erro: é a
    resposta legítima e barata que o §2.2 exige, e tratá-la como falha faria o
    Investigador insistir num documento que comprovadamente não tem o dado.
    """

    success: bool
    resposta: str = ""
    citacoes: list[str] = Field(default_factory=list)
    confianca: float = 0.0
    objeto_da_confianca: str = ""
    encontrou: bool = False
    lacuna: Optional[str] = None
    cache_hit: bool = False
    self_consistency_n: int = 1
    model: Optional[str] = None
    cost_usd: float = 0.0
    error: Optional[str] = None


class ResumirRequest(BaseModel):
    """`{doc_id, doc_hash, missao, documento_indexado}`.

    A missão é ampla de propósito: esta é a ferramenta de PRIMEIRA passada num
    documento colossal, a que o Investigador chama **antes** de perguntar, para
    saber o que perguntar (§2.2).
    """

    doc_id: str
    doc_hash: str
    missao: str = Field(description="A missão ampla — o que o Investigador quer mapear")
    documento_indexado: dict[str, Any]
    n_dinco: Optional[int] = None
    provider: Optional[str] = None
    model: Optional[str] = None


class EvidenciaResumo(BaseModel):
    """`{sid, pagina}` — a evidência do resumo, por ID.

    A `pagina` é preenchida pelo CÓDIGO a partir do `sid`, nunca pelo modelo: é
    o mesmo princípio do §6.2 (o modelo devolve o ID; o resto é lookup
    determinístico), e mata a classe "o modelo citou a folha errada para o
    trecho certo".
    """

    sid: str
    pagina: int


class ResumirResponse(BaseModel):
    """`{success, resumo, evidencias, confianca, objeto_da_confianca, …}`."""

    success: bool
    resumo: str = ""
    evidencias: list[EvidenciaResumo] = Field(default_factory=list)
    confianca: float = 0.0
    objeto_da_confianca: str = ""
    cobertura: float = 0.0
    lacunas: list[str] = Field(default_factory=list)
    cache_hit: bool = False
    self_consistency_n: int = 1
    model: Optional[str] = None
    cost_usd: float = 0.0
    error: Optional[str] = None


__all__ = [
    "EvidenciaResumo",
    "PerguntarRequest",
    "PerguntarResponse",
    "ResumirRequest",
    "ResumirResponse",
]

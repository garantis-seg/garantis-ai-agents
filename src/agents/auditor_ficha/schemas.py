"""Schemas do AUDITOR DE FICHA (S6), versao 2: dois baldes.

Decisao de 22/10/2026 (plano "ficha por IA", Parte 3, S6): o auditor deixa de
devolver so `reprovacoes` e passa a devolver o veredito do Livro da Ficha
(§10.2, regra de dois baldes):

    {"veredito": "aprovada" | "aprovada_com_correcoes" | "retida",
     "balde1": [{campo, motivo, regra, correcao_sugerida}],
     "balde2": [{campo, pendencia, grau, evidencia, recomendacao}],
     "nao_confirmado": [str],
     "alertas_respondidos": [{codigo, resposta, motivo}],
     "divergencias_gabarito": [{campo, ficha, gabarito, e_erro, motivo}]}

- Balde 1: erro objetivo que o redator corrige. Volta ao S4.
- Balde 2: juizo de substancia. NUNCA volta ao redator. Vai ao `meta` como
  pendencia.

O CODIGO calcula o veredito (ver `agent.calcular_veredito`). O modelo nao
decide o veredito.

COMPATIBILIDADE COM O SHARED (22/10/2026). O cliente atual
(`garantis_shared/fichas/auditor_ficha.py`) manda `{ficha_json, dossie: dict,
tipo}` e le `aprovado`, `reprovacoes` e `pendencias`. Por isso:

1. A entrada aceita as 3 chaves antigas e as traduz (ver
   `AuditarFichaRequest._aceitar_formato_v1`). Qualquer outra chave estranha
   reprova (`extra="forbid"`).
2. A saida mantem `aprovado` e `reprovacoes`, derivados:
   `aprovado = veredito != "retida"` e `reprovacoes = balde1` (so as 3 chaves
   do contrato). O shared migra para `veredito`/`balde1`/`balde2` na S6 do
   worker. Depois disso, os campos derivados podem sair.

V3 (23/10/2026, decisao do Alfredo). Com `nucleo`, `indice_navegavel` ou
`trilha_leitura`, o auditor vira agente sobre os autos. Cada item dos baldes traz
`prova: {doc_id, pagina, trecho}` ou `sem_prova_no_doc: true`. A saida ganha
`fatos_conferidos`. O v3 nunca recebe gabarito (Livro §10.2).
"""

import json
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, SerializeAsAny, model_validator

# 23/10/2026: o auditor v3 usa os MESMOS modelos do redator v5. O `Nucleo` e o
# `ItemIndice` seguem a forma do shared 1.826 (`v2.montar_nucleo` e
# `v2.indice_navegavel`). O teste de contrato carrega
# `tests/fixtures/nucleo_shared_1826.json` nos 2 schemas.
from ..ficha_writer.schemas import ItemIndice, Nucleo, TrilhaItem

Veredito = Literal["aprovada", "aprovada_com_correcoes", "retida"]
Grau = Literal["alta", "media", "baixa"]
RespostaAlerta = Literal["confirmado", "refutado"]

#: Limite da correcao sugerida (pedido de 22/10/2026). O auditor aponta a
#: correcao. Ele nao reescreve o campo inteiro.
MAX_CORRECAO_SUGERIDA = 300

_FECHADO = ConfigDict(extra="forbid")


# ── Entrada ────────────────────────────────────────────────────────────────


class Alerta(BaseModel):
    """Um fato que o CODIGO ja sabe e que o auditor tem de responder.

    Exemplos: "a S5 avisou A31 em bullets[3]", "o valor e estimado", "o
    gabarito diz data da sessao 24/06/2026". O auditor responde cada um com
    `confirmado` ou `refutado`, e com o motivo (plano, Parte 1.2, item 2).
    """

    model_config = _FECHADO

    codigo: str = Field(min_length=1, max_length=60)
    texto: str = Field(min_length=1, max_length=1000)


class AvisoS5(BaseModel):
    """Um achado do validador deterministico (S5), no formato `Achado`.

    O auditor recebe a lista para NAO repetir o que a S5 ja disse.
    """

    model_config = _FECHADO

    id: str
    nivel: str = "aviso"
    campo: str = ""
    mensagem: str = ""
    valor: Any = None


class AuditarFichaRequest(BaseModel):
    """Request do POST /ficha/auditar (v2).

    `ficha`, `dossie`, `gabarito`, `licoes` e os textos dos alertas sao DADO.
    O prompt cerca cada um com fence de boundary aleatorio (ver prompts.py).
    """

    model_config = _FECHADO

    ficha: dict[str, Any] = Field(
        description="A ficha inteira, redigida pelo S4 e aprovada pela S5."
    )
    esqueleto: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Os fatos que a S3b fixou com codigo: valor, datas, etapa, status, "
            "tags. E a VERDADE FIXA da auditoria. A prosa que contradiz o "
            "esqueleto vai ao balde 1."
        ),
    )
    dossie: str = Field(
        default="",
        description="O dossie congelado, em texto. A fonte de verdade da prosa.",
    )
    tipo_ficha: Optional[str] = Field(
        default=None,
        description="Tipo da S2 (nova_apolice, substituicao_fianca, ...).",
    )
    trilho: Optional[str] = Field(
        default=None,
        description="carf, estadual, ef, acoes_contribuinte ou None.",
    )
    gabarito: Optional[dict[str, Any]] = Field(
        default=None,
        description=(
            "Opcional. A ficha local aprovada do mesmo processo. O auditor "
            "compara FATOS com ela, nunca a redacao."
        ),
    )
    alertas: list[Alerta] = Field(
        default_factory=list,
        description="O que o codigo ja sabe. O auditor responde cada alerta.",
    )
    relatorio_s5: list[AvisoS5] = Field(
        default_factory=list,
        description="Os avisos da S5. O auditor nao os repete.",
    )
    licoes: list[str] = Field(
        default_factory=list,
        description="Linhas do LICOES.md da etapa S6.",
    )
    nucleo: Optional[Nucleo] = Field(
        default=None,
        description="v3: a leitura obrigatoria (o mesmo nucleo que o redator v5 leu).",
    )
    indice_navegavel: Optional[list[ItemIndice]] = Field(
        default=None,
        description="v3: o que mais existe nos autos. O auditor abre com ferramenta.",
    )
    trilha_leitura: Optional[list[TrilhaItem]] = Field(
        default=None,
        description="v3: o que o redator v5 leu para cada slot.",
    )
    provider: Optional[str] = None
    model: Optional[str] = Field(
        default=None,
        description=(
            "Override do modelo. O default e o papel `ficha_auditoria_texto`. "
            "Quem confere nao pode ser o modelo que escreveu."
        ),
    )

    @property
    def modo_v3(self) -> bool:
        return (self.nucleo is not None or self.indice_navegavel is not None
                or self.trilha_leitura is not None)

    @model_validator(mode="after")
    def _contrato_v3(self) -> "AuditarFichaRequest":
        """Regras do v3 (23/10/2026).

        - O v3 NUNCA recebe gabarito (Livro §10.2): o auditor que navega os autos
          confere contra os documentos, nao contra a ficha local.
        - O v3 exige `nucleo` e `indice_navegavel`. A `trilha_leitura` pode vir
          vazia. Meio v3 e contrato quebrado (DECIDI-SOZINHO, classe A).
        """
        if not self.modo_v3:
            return self
        if self.gabarito is not None:
            raise ValueError("v3 nunca recebe gabarito (Livro §10.2)")
        if self.nucleo is None or self.indice_navegavel is None:
            raise ValueError("v3 exige `nucleo` e `indice_navegavel` juntos")
        return self

    @model_validator(mode="before")
    @classmethod
    def _aceitar_formato_v1(cls, data: Any) -> Any:
        """Traduz o formato do cliente atual do shared para o formato v2.

        Decisao de 22/10/2026: o shared manda `ficha_json`, `dossie` como dict
        e `tipo`. Com `extra="forbid"` puro, a rota devolveria 422 para o
        cliente de hoje. A traducao vale ate o shared migrar (S6 do worker).

        Tambem aceita, por conveniencia do chamador:
        - alerta como string simples. O codigo vira `AL1`, `AL2`, ...
        - `relatorio_s5` como o objeto `Relatorio` serializado
          (`{"erros": [...], "avisos": [...]}`).
        """
        if not isinstance(data, dict):
            return data
        d = dict(data)
        if "ficha_json" in d:
            if "ficha" in d:
                raise ValueError("mande `ficha` ou `ficha_json`, nunca as duas")
            d["ficha"] = d.pop("ficha_json")
        if "tipo" in d:
            if "tipo_ficha" in d:
                raise ValueError("mande `tipo_ficha` ou `tipo`, nunca as duas")
            d["tipo_ficha"] = d.pop("tipo")
        dossie = d.get("dossie")
        if isinstance(dossie, (dict, list)):
            d["dossie"] = (
                json.dumps(dossie, ensure_ascii=False, indent=2, default=str)
                if dossie else ""
            )
        elif dossie is None:
            d["dossie"] = ""
        alertas = d.get("alertas")
        if isinstance(alertas, list):
            d["alertas"] = [
                {"codigo": f"AL{i + 1}", "texto": a} if isinstance(a, str) else a
                for i, a in enumerate(alertas)
            ]
        rel = d.get("relatorio_s5")
        if isinstance(rel, dict):
            d["relatorio_s5"] = list(rel.get("erros") or []) + list(rel.get("avisos") or [])
        elif rel is None:
            d["relatorio_s5"] = []
        return d


# ── Saida do modelo (e da rota) ────────────────────────────────────────────


class ItemBalde1(BaseModel):
    """Balde 1: erro objetivo, que o redator corrige.

    Exemplos: data de publicacao no lugar da data da sessao, numero de
    acordao trocado, fato que o dossie contradiz, vocabulario proibido em
    contexto, duas versoes do mesmo fato, prosa que contradiz o esqueleto.
    """

    model_config = _FECHADO

    campo: str = Field(description="Slot achatado: 'merito.p1', 'bullets[0]'.")
    motivo: str = Field(description="UMA frase: o que esta errado e o que o dossie diz.")
    regra: str = Field(description="ID do checklist (KC-*, H-*, V-*, ...) ou do Livro.")
    correcao_sugerida: str = Field(
        default="",
        max_length=MAX_CORRECAO_SUGERIDA,
        description="O fato certo, curto. Nao e o campo reescrito.",
    )


class ItemBalde2(BaseModel):
    """Balde 2: juizo de substancia. NUNCA vai ao redator.

    Exemplos: esgotamento duvidoso, valor do esqueleto que parece errado,
    termometro discutivel, caso que talvez nao devesse existir (kill-check).
    """

    model_config = _FECHADO

    campo: str
    pendencia: str = Field(description="A afirmacao da ficha em disputa.")
    grau: Grau
    evidencia: str = Field(description="Citacao literal do dossie, com a fonte.")
    recomendacao: str = Field(description="Acao que um humano executa.")


class AlertaRespondido(BaseModel):
    model_config = _FECHADO

    codigo: str
    resposta: RespostaAlerta
    motivo: str


class DivergenciaGabarito(BaseModel):
    """Um ponto em que a ficha e o gabarito dizem coisas diferentes.

    `e_erro=True` so para FATO (data, valor, etapa, fase, quem recorreu).
    Redacao diferente com o mesmo fato e `e_erro=False`.
    """

    model_config = _FECHADO

    campo: str
    ficha: str
    gabarito: str
    e_erro: bool
    motivo: str


# ── v3: prova de documento em cada item (23/10/2026) ───────────────────────

#: Teto do trecho da prova. O mesmo da S2c.
MAX_TRECHO_PROVA = 300


class ProvaDoc(BaseModel):
    """A prova de um item: o trecho literal do documento que refuta a ficha."""

    model_config = _FECHADO

    doc_id: str = Field(min_length=1)
    pagina: int = Field(ge=1)
    trecho: str = Field(min_length=1, max_length=MAX_TRECHO_PROVA)


class _ComProva(BaseModel):
    """Cada item do v3 traz `prova` OU `sem_prova_no_doc=true`. Nunca os dois.

    `contradiz_esqueleto` (23/10/2026): o auditor marca `true` quando o TEXTO de um
    slot contradiz um fato do esqueleto (etapa, status, data). O esqueleto é a prova:
    o código põe o item no balde 1, mesmo sem trecho de documento
    (`agent_v3.normalizar_baldes_v3`). Rodada real do IRB 1481420: 4 contradições
    com o esqueleto foram ao balde 2, e a ficha saiu aprovada.
    """

    model_config = _FECHADO

    prova: Optional[ProvaDoc] = None
    sem_prova_no_doc: bool = False
    contradiz_esqueleto: bool = False

    @model_validator(mode="after")
    def _prova_ou_sem_prova(self):
        if (self.prova is None) != self.sem_prova_no_doc:
            raise ValueError(
                "cada item traz `prova` {doc_id, pagina, trecho} OU "
                "`sem_prova_no_doc: true`, nunca os dois e nunca nenhum"
            )
        return self


class ItemBalde1V3(ItemBalde1, _ComProva):
    pass


class ItemBalde2V3(ItemBalde2, _ComProva):
    pass


class FatoConferido(BaseModel):
    """O auditor conferiu UM fato da trilha do redator contra o documento."""

    model_config = _FECHADO

    slot: str = Field(min_length=1)
    doc_id: str = Field(min_length=1)
    confere: bool
    motivo: str = Field(min_length=1, max_length=300)


class SaidaAuditor(BaseModel):
    """O JSON que o modelo devolve. Fechado: chave estranha reprova.

    `veredito` e opcional e so informativo. O codigo calcula o veredito a
    partir dos baldes (`agent.calcular_veredito`).
    """

    model_config = _FECHADO

    veredito: Optional[Veredito] = None
    balde1: list[ItemBalde1] = Field(default_factory=list)
    balde2: list[ItemBalde2] = Field(default_factory=list)
    nao_confirmado: list[str] = Field(default_factory=list)
    alertas_respondidos: list[AlertaRespondido] = Field(default_factory=list)
    divergencias_gabarito: list[DivergenciaGabarito] = Field(default_factory=list)


class SaidaAuditorV3(SaidaAuditor):
    """O JSON do modelo no v3: o do v2, com prova nos baldes e `fatos_conferidos`.

    `fatos_conferidos` é obrigatório (23/10/2026). Antes, o default `[]` deixava o
    modelo omitir a chave, e a resposta real do IRB 1481420 saiu sem fato conferido.
    """

    balde1: list[ItemBalde1V3] = Field(default_factory=list)
    balde2: list[ItemBalde2V3] = Field(default_factory=list)
    fatos_conferidos: list[FatoConferido]


class Reprovacao(BaseModel):
    """O formato v1 da reprovacao: o contrato atual do runner do shared."""

    campo: str
    motivo: str
    regra: str

    model_config = {"extra": "ignore"}


class AuditarFichaResponse(BaseModel):
    """Response do POST /ficha/auditar: o envelope da casa + o veredito v2 +
    os campos v1 derivados.

    Atencao: uma falha de chamada (`success=false`) NAO e aprovacao. Nesse
    caso `veredito` e None, `aprovado` e False e `auditor_enabled` e False.
    """

    model_config = _FECHADO

    success: bool
    veredito: Optional[Veredito] = None
    # SerializeAsAny: no v3 os itens levam `prova` e `sem_prova_no_doc`. No v2 a
    # saida fica igual (os itens sao ItemBalde1/ItemBalde2).
    balde1: list[SerializeAsAny[ItemBalde1]] = Field(default_factory=list)
    balde2: list[SerializeAsAny[ItemBalde2]] = Field(default_factory=list)
    nao_confirmado: list[str] = Field(default_factory=list)
    alertas_respondidos: list[AlertaRespondido] = Field(default_factory=list)
    divergencias_gabarito: list[DivergenciaGabarito] = Field(default_factory=list)

    # Campos v1, derivados. O shared atual le estes. Ele migra na S6 do worker.
    aprovado: bool = False
    auditor_enabled: bool = False
    modelo: Optional[str] = None
    reprovacoes: list[dict[str, Any]] = Field(default_factory=list)
    pendencias: list[str] = Field(default_factory=list)

    #: Erros da validacao da saida do modelo, no formato
    #: `{campo, erro, valor_anterior}` (plano, Parte 1.2, item 4). Vem
    #: preenchido quando a 2a rodada tambem falhou.
    erros_validacao: list[dict[str, Any]] = Field(default_factory=list)
    rodadas: int = 0
    prompt_version: str = ""
    model: str = ""
    cost_usd: float = 0.0
    error: Optional[str] = None

    #: v3 (23/10/2026): os fatos da trilha que o auditor conferiu no documento.
    fatos_conferidos: list[FatoConferido] = Field(default_factory=list)
    #: v3: os doc_id do indice que o auditor abriu, e o estado do budget.
    documentos_lidos: list[str] = Field(default_factory=list)
    chamadas_ferramenta: int = 0
    budget_esgotado: bool = False


__all__ = [
    "Alerta",
    "AlertaRespondido",
    "AuditarFichaRequest",
    "AuditarFichaResponse",
    "AvisoS5",
    "DivergenciaGabarito",
    "FatoConferido",
    "ItemBalde1",
    "ItemBalde1V3",
    "ItemBalde2",
    "ItemBalde2V3",
    "MAX_CORRECAO_SUGERIDA",
    "MAX_TRECHO_PROVA",
    "ProvaDoc",
    "Reprovacao",
    "SaidaAuditor",
    "SaidaAuditorV3",
]

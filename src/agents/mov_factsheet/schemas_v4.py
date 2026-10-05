"""Schema v4 — fatos NEUTROS do L1 (response_schema do Gemini).

NÃO substitui o `MovFactSheetCard` v3.1 — coexiste com ele, escolhido pela flag
`L1_NEUTRAL_ENABLED` (default OFF no código; ligada em prod pelo `cloudbuild-deploy.yaml`),
sob `PROMPT_VERSION_V4`. Reversível: deletar este módulo + o caminho v4 do agente volta a
100% v3.1.

DIFERENÇA CENTRAL vs v3.1: a LLM emite SÓ fatos neutros + os julgamentos genuínos
(`relevancia_merito`, `resumo_ato`). NÃO emite `sentido`/`delta_risco`/`categoria`/
`status_garantia_pos_mov`/`relevante_garantia`/`peca_pivo` — esses são DERIVED por
código (`garantis_shared.engine_v6.layer1_mov_factsheet.derivacoes`): os sujeito-
independentes no ponto comum do materializer (G6), `sentido`/`delta_risco` on-read.

O que o schema APOSENTA (mote — cada campo dropado/derivado mata um caso-especial):
  - DROP do response_schema: `tipo_origem`, `confianca`, `tipo_garantia`(top-level),
    `numero_apolice`, `relevante_garantia`(emit), `cda`, `processos_conexos_mencionados`,
    `categoria`/`status_garantia_pos_mov`/`peca_pivo`/`delta_risco`/`decisao.sentido`.
  - `valor_causa` sai do schema → S1-injetado de `leads.processos` (Q3).
  - `mov_id`/`data` NÃO são emitidos pela LLM → injetados pós-parse (materializer).

Os 6 fatos crus NOVOS em `decisao` (recorrente_polo/provido/efeito_suspensivo/
instrumento_cautelar/motivo_extincao/resultado_interlocutorio) + `requerente_polo`
DESACOPLAM extração de julgamento: a LLM relata QUEM está em cada polo e O QUE
aconteceu; o `derivar_*` decide favorável/desfavorável por `parte_seguravel`.

`cda` e conexos ficam FORA do card de mov: quem os extrai é o ramo PETIÇÃO
(`PeticaoExtractCardV4`, abaixo).

Regra de campo mora na description do campo (onde a LLM decide), não na persona; e a
persona não repete o que o constrained decoding do Gemini já força (os Literals).
"""
from __future__ import annotations

from typing import Literal, Optional, get_args

import pathlib

from .._utils.prompt_identity import versao_com_identidade

# Re-export: `agent.py` e `tests/test_peticao_extract.py` importam os dois DAQUI.
from garantis_shared.engine_v6.persistence.peticao_contract import (
    DOC_INCERTO_PROMPT_VERSION,  # noqa: F401
    PETICAO_PROMPT_VERSION,  # noqa: F401
)
from pydantic import BaseModel, Field, field_validator

# ⭐ DERIVADA, nao mantida a mao — ver `_utils/prompt_identity.py` pra a razao e as medicoes.
# ⚠️ Inclui ESTE arquivo: o schema molda a saida tanto quanto o prompt (o campo
# `dispositivo` mudou o comportamento do L1 mexendo aqui).
PROMPT_VERSION_V4 = versao_com_identidade(
    "mov_factsheet.v4.5",
    str(pathlib.Path(__file__).with_name("prompts_v4.py")),
    __file__,
)

# Taxonomia tipo_doc (34) — idêntica à v3.1 (`schemas.py` / `fundacao.TAXONOMIA_TIPO_DOC`).
# Mantida aqui pra o módulo v4 ser auto-contido/reversível; insumo de `categoria` (DERIVED).
TIPO_DOC = Literal[
    "sentenca", "acordao", "decisao_interlocutoria", "despacho", "voto",
    "peticao_inicial", "peticao", "contestacao", "recurso", "embargos",
    "contrarrazoes", "certidao", "intimacao", "citacao", "oficio", "mandado",
    "carta_precatoria", "ata_audiencia", "procuracao", "substabelecimento",
    "apolice_seguro_garantia", "fianca_bancaria", "deposito_judicial", "penhora",
    "recusa_aceitacao_garantia", "cda", "guia_recolhimento", "comprovante_pagamento",
    "planilha_calculo", "parecer", "laudo_pericial", "prova_anexa", "ilegivel", "outros",
]
_TIPO_DOC_VALORES = frozenset(get_args(TIPO_DOC))


class DecisaoBlockV4(BaseModel):
    """Fatos NEUTROS da decisão. SEM `sentido` (DERIVED on-read por parte_seguravel)."""

    tem_decisao: bool = Field(
        default=False,
        description=(
            "True SÓ se a mov contém decisão judicial material (sentença, acórdão, "
            "decisão de mérito, interlocutória, homologação). Despacho/expediente/"
            "intimação/juntada/penhora-online = false (e então natureza/recorrente/"
            "provido/resultado_interlocutorio = null)."
        ),
    )
    instancia: Optional[Literal["1g", "2g", "stj", "stf"]] = Field(
        default=None,
        description="Instância que prolatou a decisão. TST/TRT = '2g', NUNCA 'stj'. null se não identifica.",
    )
    natureza: Optional[Literal[
        "procedente", "improcedente", "parcialmente_procedente",
        "extinto_sem_merito", "homologatoria", "interlocutoria",
    ]] = Field(
        default=None,
        description=(
            "Natureza jurídica da decisão (NEUTRA — quem ganhou é derivado depois). "
            "'procedente'=pedido do AUTOR acolhido; 'improcedente'=pedido do autor rejeitado. "
            "Em Embargos/Anulatória/MS: inexigibilidade/nulidade da CDA/prescrição acolhida = "
            "'procedente' (mérito), NÃO extinto_sem_merito. Use 'interlocutoria' só p/ decisão "
            "sem mérito (liminar, tutela). Se emitir 'extinto_sem_merito', PREENCHA SEMPRE "
            "motivo_extincao (nunca deixe null)."
        ),
    )
    transito_certificado: bool = Field(
        default=False,
        description="True SÓ se a mov CERTIFICA trânsito em julgado (texto explícito).",
    )
    dispositivo: Optional[str] = Field(
        default=None,
        description=(
            "O TRECHO LITERAL do documento que decide — copiado, nunca parafraseado. "
            "É a ÂNCORA do `natureza`: sem ela, ninguém consegue verificar o veredito. "
            "Copie a frase que enuncia o desfecho (ex.: 'julgo improcedentes os embargos', "
            "'nego provimento à apelação', 'extingo o feito sem resolução do mérito'), até "
            "~300 caracteres. "
            "⛔ null quando o documento NÃO decide — inclusive quando ele apenas RELATA que "
            "houve decisão em outro ato ou em outro processo (comunicação/publicação/"
            "intimação de sentença, certidão narratória). Nesse caso `tem_decisao` também é "
            "false: a decisão pertence ao ato original, que tem movimento próprio. "
            "⛔ NÃO invente e NÃO reconstrua de memória: se você não consegue apontar a frase "
            "no texto, deixe null — null é uma resposta correta e útil."
        ),
    )
    acao_julgada_cnj: Optional[str] = Field(
        default=None,
        description=(
            "O SUJEITO da decisão: o número CNJ da AÇÃO que está sendo julgada, quando ela "
            "NÃO é a deste processo. Copie o CNJ LITERAL do próprio dispositivo/texto. "
            "⭐ null é a resposta NORMAL e correta: null significa 'a ação julgada é a deste "
            "processo', que é o caso da esmagadora maioria dos documentos. "
            "Preencha SÓ quando o documento julga OUTRA ação e diz qual — o caso típico é "
            "sentença de EMBARGOS À EXECUÇÃO trasladada para os autos da EXECUÇÃO ('julgo "
            "improcedentes os embargos à execução fiscal nº X', 'traslade-se a sentença para "
            "os autos da execução principal'). "
            "⛔ NÃO invente, NÃO deduza e NÃO reconstrua de memória: se o número não está "
            "escrito no texto, deixe null. ⛔ NÃO repita aqui o número DESTE processo. "
            "⛔ NÃO é polo, NÃO é classe e NÃO é 'quem ganhou' — é só o ponteiro para a ação."
        ),
    )
    # ── fatos crus NOVOS (neutros) — desacoplam extração de julgamento ──
    recorrente_polo: Optional[Literal["ativo", "passivo"]] = Field(
        default=None,
        description=(
            "Em decisão de RECURSO: QUAL POLO recorreu (neutro — 'ativo' OU 'passivo', "
            "NÃO 'o cliente'). Identifique pelo texto quem é o recorrente/apelante/agravante "
            "e em qual polo ele está. null se não é recurso ou não dá pra identificar."
        ),
    )
    provido: Optional[Literal["sim", "nao", "parcial", "sem_julgamento"]] = Field(
        default=None,
        description=(
            "Resultado do recurso: 'sim'=provido, 'nao'=não provido/negado/improvido, "
            "'parcial'=parcialmente provido, 'sem_julgamento'=não conhecido/preliminar. "
            "null se não é recurso."
        ),
    )
    efeito_suspensivo: Optional[bool] = Field(
        default=None,
        description=(
            "True se o recurso/decisão tem efeito SUSPENSIVO (suspende os efeitos da decisão "
            "recorrida, ex: apelação CPC 1.012). null se n/a."
        ),
    )
    instrumento_cautelar: Optional[Literal[
        "suspensao_seguranca", "suspensao_exigibilidade_ctn", "nenhum",
    ]] = Field(
        default=None,
        description=(
            "Instrumento cautelar ESPECÍFICO presente: 'suspensao_seguranca'=suspensão de "
            "segurança (Lei 8.437/12.016, requerida pelo ENTE PÚBLICO à presidência do tribunal "
            "p/ sustar liminar — NÃO confunda com MS/liminar genérica); "
            "'suspensao_exigibilidade_ctn'=suspensão da exigibilidade do crédito tributário "
            "(art. 151 CTN — depósito/parcelamento/liminar do contribuinte); 'nenhum'/null caso contrário."
        ),
    )
    resultado_interlocutorio: Optional[Literal["deferida", "indeferida"]] = Field(
        default=None,
        description=(
            "SÓ para TUTELA/LIMINAR/medida cautelar SUBSTANTIVA OU instrumento_cautelar: foi "
            "'deferida'(concedido) ou 'indeferida'(negado)? NÃO preencha para despacho de mero "
            "impulso (deferir inicial/citação/penhora/prazo) — esses não são tutela. null se n/a."
        ),
    )
    requerente_polo: Optional[Literal["ativo", "passivo"]] = Field(
        default=None,
        description=(
            "Quando há tutela/liminar (resultado_interlocutorio preenchido): QUAL POLO PEDIU a "
            "medida (ativo OU passivo, neutro). Ex: 'deferida a tutela ao autor' → ativo. null "
            "para impulso procedimental ou se não dá pra identificar."
        ),
    )
    motivo_extincao: Optional[Literal[
        "terminativa", "consensual", "satisfacao", "nenhum",
    ]] = Field(
        default=None,
        description=(
            "OBRIGATÓRIO quando natureza='extinto_sem_merito' (nunca null nesse caso): "
            "'terminativa'=extinção processual (ilegitimidade/abandono/prescrição acolhida em "
            "exceção); 'consensual'=desistência/acordo homologado; 'satisfacao'=extinção por "
            "PAGAMENTO/quitação/satisfação da obrigação (art. 924 II CPC). "
            "null SÓ quando a natureza não é extinto_sem_merito."
        ),
    )


class EventoGarantiaV4(BaseModel):
    """Evento envolvendo a garantia/apólice. `subtipo` recebe o ex-`tipo_garantia` (top-level)."""

    tipo: Literal[
        "apresentacao", "aceitacao", "recusa", "levantamento",
        "substituicao", "reforco", "acionamento", "nenhum",
    ] = Field(
        default="nenhum",
        description=(
            "Evento envolvendo a garantia/apólice: 'apresentacao'/'aceitacao'/'recusa'/"
            "'levantamento'(restituição AO privado)/'substituicao'/'reforco'; "
            "'acionamento'=ordem de EXECUTAR/converter a garantia em pagamento (intime-se a "
            "garantidora a pagar/depositar); 'nenhum' quando a mov não trata de garantia."
        ),
    )
    motivo: Optional[str] = Field(
        default=None,
        description="Quando tipo='recusa': motivo explícito (ex: 'valor insuficiente'). null caso contrário.",
    )
    subtipo: Optional[Literal[
        "seguro_garantia", "fianca_bancaria", "carta_fianca",
        "deposito_judicial", "penhora", "fiduciaria", "outras",
    ]] = Field(
        default=None,
        description="Tipo da garantia, SÓ quando há evento de garantia. null caso contrário.",
    )


class ValoresBlockV4(BaseModel):
    """Valores monetários (S3 puro — só o que o texto sustenta). `valor_causa` = S1-injetado."""

    valor_debito_executado: Optional[float] = Field(
        default=None,
        description="Valor do débito executado em BRL quando explícito. null caso contrário.",
    )
    valor_garantia: Optional[float] = Field(
        default=None,
        description="Valor da garantia/apólice em BRL quando explícito. null caso contrário.",
    )
    # valor_causa: S1-injetado no materializer de leads.processos (Q3) — NÃO emitido pela LLM.


class MovFactSheetCardV4(BaseModel):
    """response_schema do Gemini (v4) — SÓ fatos neutros + julgamentos genuínos.

    Identidade (`mov_id`/`data`) NÃO é emitida pela LLM — é injetada pós-parse pelo
    agente/materializer. Os campos DERIVED (categoria/status_garantia_pos_mov/
    relevante_garantia/peca_pivo/sentido/delta_risco) são computados por
    `derivacoes` fora deste schema (ponto comum G6 + on-read).
    """

    resumo_ato: str = Field(
        description=(
            "Resumo PT-BR (português ACENTUADO normal — é o único campo de texto livre "
            "com acento) do que aconteceu NESTA mov. Tamanho proporcional à relevância: "
            "ato trivial = 1 frase; decisão/sentença/evento de garantia = até ~300 palavras "
            "se houver substância. Técnico-jurídico, neutro. NÃO repita o resumo do processo."
        ),
    )
    tipo_doc: TIPO_DOC = Field(description="Tipo da peça/documento — UM da taxonomia (34 valores).")
    relevancia_merito: Literal["alta", "media", "baixa", "ruido"] = Field(
        description=(
            "Quanto este ato influencia a TESE/MÉRITO: 'alta'=decisão/sentença/acórdão/evento "
            "de garantia/intimação de pagamento/trânsito; 'media'=peças recursais/saneadores; "
            "'baixa'=despachos ordinatórios/publicações; 'ruido'=cargas/baixas sem conteúdo."
        ),
    )
    decisao: DecisaoBlockV4 = Field(default_factory=DecisaoBlockV4)
    evento_garantia: EventoGarantiaV4 = Field(default_factory=EventoGarantiaV4)
    valores: ValoresBlockV4 = Field(default_factory=ValoresBlockV4)
    data_inferida_ato: Optional[str] = Field(
        default=None,
        description=(
            "YYYY-MM-DD do ato real INFERIDA do texto (ex: 'sentença proferida em "
            "10/03/2024'), SOMENTE quando diferir da data de publicação da mov E houver "
            "data explícita no texto. É inferência da LLM, não dado autoritativo. "
            "null em todos os outros casos (NÃO repita a data da publicação)."
        ),
    )

    @field_validator("decisao", "evento_garantia", "valores", mode="before")
    @classmethod
    def _null_block_to_default(cls, v):
        # O Gemini às vezes emite estes blocos aninhados como null EXPLÍCITO (chave
        # presente, valor None) em vez de omiti-los. `default_factory` só vale quando a
        # chave está AUSENTE — null vira "Input should be a valid dictionary or instance
        # of <Block>" e o parse falha -> 500 -> retry storm do L1. Semanticamente null ==
        # "sem decisão / sem evento de garantia / sem valores" == o bloco default vazio.
        return {} if v is None else v

    @field_validator("tipo_doc", mode="before")
    @classmethod
    def _coerce_tipo_doc_desconhecido(cls, v):
        # Mesma família do _null_block_to_default: a LLM emite tipo_doc FORA da taxonomia
        # (ex 'relatorio_fiscal' em exec-fiscal — sem constrained-decoding no ramo não-
        # petição) -> literal_error -> 500 -> retry storm; em mérito de 1 mov isso é 100%
        # de L1 fail -> l1_degraded -> indeterminado. 'outros' é o catch-all do próprio
        # enum ("não se encaixa em nenhum").
        if isinstance(v, str) and v not in _TIPO_DOC_VALORES:
            return "outros"
        return v


# ════ Ramo PETIÇÃO INICIAL (peticao_extract) — formacao de conexos ════
# Variacao da L1: mesmo card v4 + os campos do CONTRATO do leitor-de-peticao.
# Versionamento POR RAMO: bump daqui NÃO invalida cache do mov_factsheet (e vice-versa).
# Caller opt-in via classe="peticao" (o materializer da peticao no garantis-shared).
#
# ⛔ O enforcement real e DETERMINISTICO no sink/formacao do garantis-shared, nao aqui: o
# CNJ so vale com os 20 digitos no texto-fonte + mod-97, e `papel` e HINT — nunca cria
# aresta sozinho. O prompt so reduz o ruido (formato CNJ obrigatorio, "so o que esta NO
# DOCUMENTO", artigo de lei nao e CDA, sem esticar RE/AREsp/ADI pra 20 digitos).
# ⛔ Nao afirmar o que nao sabe (decisao do Elton): `pa` (esfera INDETERMINADA) e o DEFAULT;
# `paf`/`tit_sp`/`pa_estadual` sao AFIRMACOES, so com sinal no texto (orgao nomeado ou
# mascara). `pa` mapeia em (esfera NULL, uf NULL) no ADMIN_TIPO_TO_NO => badge "A
# classificar", nao "Adm. Fed.".
# ⭐ Rotulo sem nome pro caso FORCA o rotulo errado: com `tit_sp` como UNICO nome do enum pra
# "auto de infracao estadual", a LLM o usava mesmo lendo outro estado no documento inteiro —
# nao era janela de contexto, era DESENHO DE ROTULO. Por isso `tit_sp` EXIGE Sao Paulo
# NOMEADO no texto (o espelho LITERAL da regra que ja disciplina `pa_estadual`).
# ⛔ A UF e ATRIBUTO do no (`uf` + `uf_evidencia`, ver `ProcessoAdminCitado` ->
# `leads.admin_items.uf`), NUNCA rotulo novo por estado. Literal e nao `str` de proposito: da
# constrained decoding e mata 'SPO'/'S.P' na ORIGEM, que e o valor que o `varchar(2)`
# rejeitaria com excecao dentro do savepoint do sink.
# ⚠️ Pra medir o efeito: `telemetria.engine_llm_calls.prompt` NAO retem a peca do L1 (o unico
# texto retido e o do `layer2_processo_synthesis`), e 'Tribunal de Impostos e Taxas'/
# 'SEFAZ-SP' estao no TEMPLATE do prompt — nao servem de discriminador.
# 🚨 O bump da versao ARMA a onda de releitura: `backfill-peticao-daily` roda com
# `reextract_stale`, e o SWAP-POR-PN do sink troca as rows da versao velha de cada pn (mexe
# no grafo de conexos). E mudanca deliberada em massa que altera saida de risco.
# ⚠️ ARMA, nao dispara: o filtro roda no fe-api sobre `_CURRENT_PETICAO_VERSIONS`, que vem do
# wheel PINADO em `frontend-api/requirements.txt`. Mergear/publicar o shared nao move card
# nenhum — quem dispara e o **bump do pin do fe-api + deploy**. ⛔ E o inverso tambem: bumpar
# o pin "so pra atualizar dependencia" DISPARA a onda.
# ⚠️ Os 2 VALORES (`PETICAO_PROMPT_VERSION` e `DOC_INCERTO_PROMPT_VERSION`) moram no
# garantis-shared (`engine_v6.persistence.peticao_contract`) e sao IMPORTADOS no topo deste
# arquivo — sao lidos por TRES processos e o fe-api nao importa este repo, entao literal aqui
# vira drift la. Bump = editar LA e re-publicar o wheel; o changelog vai no commit/PR.
# Ramo 1X: doc de tipo NAO identificado (fallback L3 do identify) — mesmo
# schema superset do 1P (tipo_doc classificado em vez de cravado). Versao por
# ramo: bump do 1X nao invalida cache do 1P nem do mov, e vice-versa.
# ⛔ O schema (`PeticaoExtractCardV4`) e COMPARTILHADO pelo 1P e pelo 1X: campo/enum novo
# chega nos DOIS querendo ou nao, e campo que o prompt nao explica sob constrained decoding e
# pior que campo ausente ⇒ as DUAS prompts (`prompts_v4.py`, blocos admin do 1P e do 1X)
# mudam juntas.
# Campo ADITIVO sem bump de versao, DE PROPOSITO (`valor_causa_declarado`/
# `valor_causa_evidencia`; o `papel` dos itens admin): o bump arma a onda, e o estoque que
# precisa do campo vai por releitura DIRIGIDA (`force_reextract` no `/materialize-peticao`).
# O card segue IDENTIFICAVEL pela chave nova; card sem ela = "nao medido", nunca "a peca nao
# declara" (item admin sem `papel` segue virando vizinho). O proximo bump, por outra razao,
# popula o acervo de graca.
# ⚠️ O `papel` tem um preco aceito do sem-bump: a regra "numero de ACORDAO nao e numero de PA"
# muda o que entra num campo ANTIGO (`processos_administrativos_citados`), e card SEM item
# admin nao separa "antes" de "depois". Se alguem passar a ler essa diferenca, e o caso de
# bumpar (e o bump arma a onda).
# ⛔ E o ESTOQUE gravado como numero de acordao NAO se corrige por releitura: o prompt novo nao
# re-emite o numero (o sink nunca mais toca aquela referencia) e a releitura na MESMA versao
# nao faz swap — ela fica "nao medida" = vizinho, ponte possivel. Desanexar a mao volta no
# proximo resolve (anexo de orfao e livre). A limpeza e a do recibo da Receita (fe-api, mig
# `20260814_2200`): DELETE da membership E da referencia, com backup `zz_`; o cinto `rejected`
# sozinho nao segura (e direcional, pelo merito da semente).


class CdaPeticao(BaseModel):
    """CDA/inscrição em dívida ativa que ESTE processo executa/discute (corpo/planilha
    da petição inicial). Conector 'irmãos' da formação de conexos — taxpayer-specific,
    forte e confiável."""

    numero: str = Field(description="Número LITERAL da CDA/inscrição como aparece no texto.")
    ente: Optional[Literal["estadual", "municipal", "federal_pgfn"]] = Field(
        default=None, description="Origem da CDA. null se não identifica.",
    )
    tributo: Optional[str] = Field(
        default=None, description="Sigla do tributo (ICMS, ISS, IPVA, IRPJ...). null se não identifica.",
    )
    valor_total: Optional[float] = Field(
        default=None, description="Valor em BRL quando explícito. null caso contrário.",
    )


class ProcessoCitado(BaseModel):
    """Processo citado na petição inicial. O campo crítico é `papel` — conector
    'derivados' (citação-direcional) da formação de conexos."""

    cnj: str = Field(description="CNJ citado LITERALMENTE (20 dígitos ou formatado 7-2.4.1.2.4).")
    papel: Literal["originario", "derivado", "incidente", "jurisprudencia", "incerto"] = Field(
        description=(
            "'originario'=o contexto indica o processo de ORIGEM desta ação ('distribuição "
            "por dependência', 'Processo de Origem', 'nos autos da Execução Fiscal nº', 'em "
            "apenso a') — sinal de ouro; 'jurisprudencia'=CNJ em ementa/precedente citado "
            "('Rel. Des.', 'Relator:', 'Data de Julgamento', Turma/Câmara); 'derivado'/"
            "'incidente'=ação derivada/incidental mencionada; 'incerto'=não dá pra classificar "
            "(a integração decide)."
        ),
    )
    contexto: Optional[str] = Field(
        default=None,
        description="Snippet ~120 chars ao redor da citação (pra auditoria do papel).",
    )


class ProcessoAdminCitado(BaseModel):
    """Processo ADMINISTRATIVO citado na petição (PAF/RFB federal ou AIIM/TIT estadual SP).
    Conector cross-type J->A da formação de conexos — taxpayer-specific. (WS-D 2026-06-27.)

    ⚠️ `tipo` é CONTRATO cross-repo: ele vira a coluna `leads.admin_items.tipo` (metade do
    UNIQUE (tipo, numero_normalizado)) E a ESFERA do nó, via
    `garantis_shared...peticao_contract.ADMIN_TIPO_TO_NO`. Valor novo aqui sem entrada lá
    cai em `paf`/federal. `tests/test_enum_contrato_sink.py` cruza os dois lados.

    ⚠️ A UF do nó NÃO vem mais do `tipo` (desde 2026-08-14) e passou a vir do campo `uf`
    abaixo (R2, 2026-08-19, card 869ekv7b9) — CLAIM com evidência ancorada, resolvida
    sobre o conjunto de claims daquele número pelo `resolve_admin_uf` do shared. ⛔ Ela
    NUNCA se deriva do rótulo nem do tribunal: medido em prod, 144 de 269 refs `tit_sp`
    (53,5%) estão fora da própria máscara AIIM e 98 em tribunal estadual de OUTRO estado.
    ⛔ E não se cria rótulo por estado (`tit_mg`, ...): a lista de 9 `item_type` é
    contrato com o parceiro (decisão Elton). O estado é ATRIBUTO, não rótulo.

    ⚠️ Nem todo PA citado é conector da disputa (card 869fay0p0, 2026-10-02): o acórdão do
    CARF/CSRF/TIT citado como PRECEDENTE é jurisprudência — o caso que abriu isto foi o PA
    de outro contribuinte que virou membro da Grendene e ponte de fusão com a WestRock. Por
    isso o `papel` abaixo: o sink do shared grava todos, e o gather do conexo (fe-api)
    deixa de fora os de `peticao_contract.PAPEIS_ADMIN_NAO_VIZINHO`. Ausente = não medido.
    """

    numero: str = Field(description="Número LITERAL do processo administrativo como aparece no texto.")
    tipo: Literal["pa", "paf", "tit_sp", "pa_estadual"] = Field(
        default="pa",
        description=(
            "'pa'=processo administrativo cuja ESFERA o documento não deixa clara — é o "
            "DEFAULT; na dúvida sobre o órgão use 'pa' e NÃO afirme federal só porque o "
            "número parece um NUP. 'paf'=fiscal FEDERAL AFIRMADO: o texto nomeia órgão "
            "federal (Receita Federal/RFB, CARF, DRJ, PGFN) OU o número está na máscara NUP "
            "NNNNN.NNNNNN/AAAA-DD (5+6 dígitos antes da barra); do número NÃO dá pra afirmar "
            "CARF. 'tit_sp'=AIIM/auto de infração de SÃO PAULO (N.NNN.NNN-D) — exige que o "
            "texto NOMEIE São Paulo (Tribunal de Impostos e Taxas, SEFAZ-SP, DRT, Secretaria "
            "da Fazenda do Estado de São Paulo). Auto de infração ESTADUAL sem São Paulo "
            "nomeado NÃO é 'tit_sp': use 'pa_estadual' (fisco estadual nomeado) ou 'pa'. "
            "'pa_estadual'=processo administrativo de fisco ESTADUAL (Secretaria da Fazenda "
            "de um estado; verificação fiscal, defesa/recurso administrativo) — o PROCESSO, "
            "não o auto: se o número é do AIIM PAULISTA use 'tit_sp'. Só marque quando o "
            "texto disser o ÓRGÃO estadual."
        ),
    )
    contexto: Optional[str] = Field(
        default=None, description="Snippet ~120 chars ao redor da citação (auditoria).",
    )
    uf: Optional[Literal[
        "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
        "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC",
        "SP", "SE", "TO",
    ]] = Field(
        default=None,
        description=(
            "Sigla do ESTADO do órgão que instaurou/lavrou o processo, SÓ quando o texto "
            "NOMEIA o estado ou o órgão estadual (ex.: 'SEF/MG', 'SEFAZ-SP', 'Secretaria de "
            "Estado de Fazenda de Minas Gerais'). ⛔ NUNCA derive do tribunal onde o processo "
            "JUDICIAL tramita, nem do tipo do item: onde o auto é discutido não diz de quem "
            "ele é. null quando o texto não nomeia o estado — que é o caso normal."
        ),
    )
    uf_evidencia: Optional[str] = Field(
        default=None,
        description=(
            "Snippet ~120 chars copiado do texto onde o estado/órgão estadual é NOMEADO. "
            "Obrigatório sempre que `uf` for preenchida: a integração DESCARTA a uf cujo "
            "snippet não nomeie o estado. null quando uf=null."
        ),
    )
    par_numero: Optional[str] = Field(
        default=None,
        description=(
            "Quando o texto apresenta o PAR 'Processo Administrativo nº X (AIIM nº Y)', o "
            "número LITERAL do OUTRO item do par. Emita os DOIS como itens separados, cada "
            "um com par_numero apontando pro outro. null quando o número aparece sozinho."
        ),
    )
    # Consumido por NOME de chave no sink do garantis-shared
    # (`peticao_sink._papel_por_numero`) e cruzado com o contrato em
    # `tests/test_enum_contrato_sink.py`. Optional e default None DE PROPÓSITO: None = "não
    # medido", o mesmo que o card de antes do campo é — e segue virando vizinho, como hoje.
    # ⚠️ ÚLTIMO campo de propósito: a ordem dos campos é a ordem da saída sob constrained
    # decoding, então os campos antigos saem como antes e o papel é decidido DEPOIS do
    # `contexto` que o audita.
    papel: Optional[Literal["discutido", "precedente", "incerto"]] = Field(
        default=None,
        description=(
            "O PAPEL deste processo administrativo NESTA ação, pelo CONTEXTO da citação. "
            "'discutido'=o PA que esta ação discute ou de que depende (o auto de infração/"
            "lançamento impugnado, a compensação/PER-DCOMP, o pedido de restituição/crédito, "
            "a cobrança da CDA executada), inclusive quando a peça cita o acórdão proferido "
            "NESSE PA. 'precedente'=PA citado como JURISPRUDÊNCIA: a decisão de OUTRO processo "
            "trazida pra sustentar a tese, em geral de outro contribuinte — SÓ com assinatura "
            "de jurisprudência na citação (Acórdão nº, Relator/Conselheiro, ementa, Turma/"
            "Câmara, sessão de julgamento). 'incerto'=sem ligação explícita com esta ação e "
            "sem essa assinatura, ou o texto não deixa dizer — nunca 'precedente' por falta de "
            "sinal. null só se não houver contexto nenhum."
        ),
    )


class PeticaoExtractCardV4(MovFactSheetCardV4):
    """response_schema do ramo PETIÇÃO: o card v4 + extração dirigida de conectores.

    Herda todos os campos do MovFactSheetCardV4 (resumo_ato/tipo_doc/relevancia/decisao/
    evento_garantia/valores/data_inferida_ato) — a petição NÃO tem decisão (tem_decisao
    =false por instrução), mas PODE ter evento_garantia (oferta de garantia na inicial).
    Persistência: o JSONB carrega os campos extras; a tabela tipada ignora (tolerante);
    o sink FASE 4 consome cdas/processos_citados → processo_referencias/processo_conexoes.
    """

    cdas: list[CdaPeticao] = Field(
        default_factory=list,
        description="CDAs que ESTE processo executa/discute. [] se nenhuma no texto.",
    )
    processos_citados: list[ProcessoCitado] = Field(
        default_factory=list,
        description="Processos citados na petição, com papel. [] se nenhum.",
    )
    processos_administrativos_citados: list[ProcessoAdminCitado] = Field(
        default_factory=list,
        description="Processos administrativos (PAF/RFB federal, AIIM/TIT SP) citados na petição. [] se nenhum.",
    )
    confianca_extracao: float = Field(
        default=0.7, ge=0.0, le=1.0,
        description=(
            "Confiança na EXTRAÇÃO dos conectores (0-1): texto limpo e citações claras "
            "= alta; OCR ruidoso/citações ambíguas = baixa. (Escopo: só cdas/processos_"
            "citados — não os demais campos do card.)"
        ),
    )
    # Consumidos por NOME de chave no sink do garantis-shared
    # (`peticao_sink.valor_causa_ok`) — renomear aqui cala o ramo lá sem erro nenhum.
    valor_causa_declarado: Optional[float] = Field(
        default=None,
        description=(
            "VALOR DA CAUSA que a própria petição DECLARA ('Dá-se à causa o valor de R$ X', "
            "'Valor da causa: R$ X'). Se uma EMENDA o retifica, o da EMENDA. É o valor "
            "atribuído à CAUSA — não o débito executado, não a garantia, não o valor de "
            "uma CDA. null se a peça não declara."
        ),
    )
    valor_causa_evidencia: Optional[str] = Field(
        default=None,
        description=(
            "Snippet ~120 chars copiado LITERALMENTE do texto onde o valor da causa é "
            "declarado, com o número como está escrito. Obrigatório sempre que "
            "`valor_causa_declarado` for preenchido. null quando ele for null."
        ),
    )

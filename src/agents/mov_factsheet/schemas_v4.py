"""Schema v4 — fatos NEUTROS do L1 (response_schema do Gemini). FASE 2 / shadow.

Porte do contrato congelado §1h (`~/.claude/plans/l1-fase1-contrato-2026-06-09.md`),
validado end-to-end pelo piloto zero-deploy 2026-06-09 (`_l1_pilot/schema_v4.py` +
cascata L1->L2->L3 vs Poletto). NÃO substitui o `MovFactSheetCard` v3.1 — coexiste
sob `PROMPT_VERSION="mov_factsheet.v4"` + flag (default OFF). Reversível: deletar este
módulo + o caminho v4 do agente volta a 100% v3.1.

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

DEFER (re-liga no Lote 3 / FASE 4, leitor-de-petição): `cda`, conexos.
"""
from __future__ import annotations

from typing import Literal, Optional, get_args

from garantis_shared.engine_v6.persistence.peticao_contract import (
    DOC_INCERTO_PROMPT_VERSION,
    PETICAO_PROMPT_VERSION,
)
from pydantic import BaseModel, Field, field_validator

# v4.1 (2026-06-11, prompt-review Lote 1 — itens 1.1/1.2 do kickoff):
#   1.1 persona/REGRA DE OURO reescritas: a tarefa real é resolver ator-do-texto →
#       polo USANDO o CONTEXTO injetado (a composição dos polos não é descoberta).
#   1.2 'ENUMs em ASCII' removida da persona (o response_schema/constrained decoding
#       do Gemini já força os Literals — verificado: 0 enum inválido em 40 casos ×
#       múltiplos runs sem a instrução); 'só resumo_ato leva acento' movida pra
#       description do campo (regra de campo mora no campo).
#   + 'Echo de mov_id' removido (instrução morta: o schema v4 não tem mov_id —
#       identidade é injetada pós-parse).
# Gate: gate_v4.py (3-run majority vs baseline master, casos _boundary ignorados).
# v4.2 (2026-06-11, prompt-review parte 3 — decisões D + G aprovadas na sessão):
#   D: bloco RESUMO DO PROCESSO removido do prompt (dependência resumo_ia/Escavador
#      não garantida; era contexto de fundo). Se a qualidade dos 1A degradar,
#      re-adicionar é a melhoria futura. lazy_gen upstream NÃO tocado.
#   G: drops aprovados do schema — valor_excluido + percentual_mantido (0/10
#      preenchidos quando aplicáveis E 0 leitores no código) e data_real_ato
#      (73,8% redundante com `data`; 0 leitores reais — só passthrough/debug).
#      Colunas da tabela tipada ficam (viram NULL em cards novos); shared lê via
#      .get() tolerante — zero mudança fora deste módulo.
# Gate: gate_v4.py 3-run majority vs baseline v4.1.
# v4.3 (2026-06-11, prompt-review parte 4 — decisões #2/#6 aprovadas na sessão):
#   - motivo_extincao OBRIGATÓRIO quando extinto_sem_merito (censo 4.2: 0/15 preenchidos
#     — degradava SENTIDO_EXTINCAO on-read). Regra movida pra description de natureza
#     (onde a LLM decide) + goldens de extinção novos (polo_regression 11-15).
#   - data_inferida_ato: volta do data_real_ato RENOMEADO (decisão G.2 — é inferência,
#     não dado autoritativo; emitir SÓ quando difere da publicação). Coluna tipada segue
#     data_real_ato até follow-up no shared (0 leitores).
#   - VOCAB fiscal: regra da EXCEÇÃO DE PRÉ-EXECUTIVIDADE (carimbo jurídico Alfredo
#     2026-06-11): acolhida ≠ 'procedente' (evita inversão de sinal — o autor da EF é a
#     Fazenda); escopo das regras de inexigibilidade restrito a Embargos/Anulatória/MS.
#   - Ramo DOCUMENTO (ex-órfão) fechado: ganha VOCAB_FAMILIA + REGRAS_CRUS + metadata
#     do doc (tipo|titulo|data|provider — censo: metadata jusbrasil 100% preenchida) +
#     wording 'DOCUMENTO AVULSO'.
# v4.4 (2026-06-11, prompt-review parte 5 — GO do "sem limite" / item J original):
#   - Removidos os caps de exibição do ramo MOVIMENTO: 5 docs/mov e 8.000 chars/doc
#     viram ORÇAMENTO por unidade (_V4_DOCS_BUDGET=2M chars, teto 1M/doc — guarda de
#     janela, não economia). Excedente vira marcador explícito (no silent caps).
#   - Snippet da mov: 3.000 -> 200.000 chars (publicação pode trazer inteiro teor).
#   - Ramo DOCUMENTO (1D): 8.000 -> 1M chars.
#   - Par com garantis-shared: fetch DOC_TEXT_CAP_CHARS 8k->1M + apply_docs_unit_budget
#     na montagem do payload (efeito completo SÓ após publish do shared + bump dos pins
#     em ai-agents/fe-api/worker; antes disso o texto chega capado a 8k do fetch).
#   - v3.1 INTOCADO (cap próprio de 8k no render). day_factsheet (caps 20/8/6k SQL)
#     fora do escopo — follow-up próprio (prompt agregado por dia, orçamento distinto).
#   - Custo: censo 2026-06-10 mediu ~8,9x de input sem cap — decisão qualidade>custo.
# v4.5 (2026-06-22, L1 misread triage sessão gabi/Poletto): _REGRAS_CRUS (prompts_v4)
#   ganhou regra natureza/tem_decisao "classifique pelo ATO, não pelo que transcreve":
#   (a) Embargos de Declaração (acolhidos/rejeitados) => natureza='interlocutoria' (NÃO
#   copiar improcedente da decisão embargada) — conserta M1; (b) certidão de inteiro teor/
#   relatório de andamento => tem_decisao=false — conserta M2. Validado offline v4 4/4 em
#   ED + certidão, control (acórdão de mérito real) preservado improcedente/e_pivo=true.
#   derivar_e_pivo já trata interlocutoria/tem_decisao=false => e_pivo=false (sem mudar
#   derivacoes). Ver memory l1-misread-m1-load-m2-orfao.
PROMPT_VERSION_V4 = "mov_factsheet.v4.5"

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
        # of <Block>" e o parse falha -> 500 -> retry storm do L1 (erro DOMINANTE do
        # cascade: ~56% dos 500 do ai-agents em 2026-06-15). Semanticamente null ==
        # "sem decisão / sem evento de garantia / sem valores" == o bloco default vazio.
        return {} if v is None else v

    @field_validator("tipo_doc", mode="before")
    @classmethod
    def _coerce_tipo_doc_desconhecido(cls, v):
        # Mesma família do _null_block_to_default: a LLM emite tipo_doc FORA da taxonomia
        # (ex 'relatorio_fiscal' em exec-fiscal — sem constrained-decoding no ramo não-
        # petição) -> literal_error -> 500 -> retry storm; em mérito de 1 mov isso é 100%
        # de L1 fail -> l1_degraded -> indeterminado (raiz dos 9 méritos travados
        # 2026-06-17). 'outros' é o catch-all do próprio enum ("não se encaixa em nenhum").
        if isinstance(v, str) and v not in _TIPO_DOC_VALORES:
            return "outros"
        return v


# ════ Ramo PETIÇÃO INICIAL (peticao_extract.v1) — FASE 4 conexos ════
# Variação da L1 (decisão Elton/Alfredo 2026-06-11): mesmo card v4 + os campos do
# CONTRATO do leitor-de-petição (prompts/fase4-alfredo-handoff-peticao-extraction.md).
# Versionamento POR RAMO: bump daqui NÃO invalida cache do mov_factsheet (e vice-versa).
# Caller opt-in via classe="peticao" — o materializer de prod NUNCA envia isso hoje;
# zero mudança de comportamento até a integração ligar (sink FASE 4).

# v1.1 (2026-06-11, 1a iteracao com dado real — review Casas Bahia/Alfredo): o v0
# extraia QUALQUER numero juridico como processo (40/58 eram artigos de lei, incl.
# vazados do proprio template: CPC 1.012/art.924/Lei 8.437 das descriptions; e 1 blend
# alucinado de 2 CNJs). Fix: formato CNJ obrigatorio + "so o que esta NO DOCUMENTO" +
# artigo de lei nao e CDA. Rede determininistica complementar no sink: digitos do cnj
# devem existir no texto-fonte + len==20 + mod-97.
# v1.2 (2026-06-12, 2a iteracao — auditoria Fable das 6 peticoes + decisao Alfredo):
# 2 ocorrencias de papel relacional em precedente (paradigma trabalhista->originario;
# Intermedium->derivado = unica aresta falsa do insumo da formacao). Fix por
# ESPECIFICACAO da regra existente (nao regra nova): originario nega paradigma/prova
# emprestada explicitamente; derivado/incidente exige MESMA empresa/parte privada
# (parte publica varia: Fazenda/autoridade coatora — assimetria do MS apontada pelo
# Alfredo); na duvida 'incerto' (a integracao decide com company-coherence). + anti-
# esticamento (nao converter RE/AREsp/ADI pra 20 digitos). Enforcement real continua
# DETERMINISTICO no sink/formacao (papel = hint, nunca cria aresta sozinho).
# v1.3 (2026-06-27, WS-D): + processos_administrativos_citados[] (PAF/RFB federal + AIIM/TIT SP)
# como conector cross-type J->A do 1.B. Bump invalida o cache v1.2 -> re-extrai 1x com admin.
# v1.4 (2026-08-07, tasks 869efg29g + 869efg29k): (a) o PAR "Processo Administrativo n X
# (AIIM n Y)" vira DOIS itens, cada um com `par_numero` apontando pro outro — ate aqui o
# AIIM do parentese se perdia, e com ele a aresta que ligaria os conexos (elo que faltou no
# QA do Kelveng, MS Steel Rol); (b) tipo='pa_estadual' pro PA de fisco ESTADUAL, que o enum
# binario forcava a `paf` => esfera federal (caso vivo: 017.00100686/2026-51 instaurado
# perante a SEFAZ-SP aparecia como "ADM. FED." no conexo 1477176). Bump invalida o cache
# v1.3 -> re-extrai 1x; o SWAP-POR-PN do sink troca as rows da versao velha DESTE pn, entao
# o legado se re-tipa sozinho conforme cada peticao e re-lida.
# ⚠️ Os 2 VALORES (`PETICAO_PROMPT_VERSION` = peticao_extract.v1.4 e
# `DOC_INCERTO_PROMPT_VERSION` = doc_incerto_extract.v1.2) moram no garantis-shared
# (`engine_v6.persistence.peticao_contract`) e sao IMPORTADOS no topo deste arquivo —
# sao lidos por TRES processos e o fe-api nao importa este repo, entao literal aqui
# vira drift la (ja custou 896 cards re-pagos + 1.039 nunca refrescados). Bump =
# editar LA, re-publicar o wheel, e escrever o changelog AQUI, junto da prompt.
# Ramo 1X: doc de tipo NAO identificado (fallback L3 do identify) — mesmo
# schema superset do 1P (tipo_doc classificado em vez de cravado). Versao por
# ramo: bump do 1X nao invalida cache do 1P nem do mov, e vice-versa.
# v1.2 (2026-08-07): mesma mudanca do 1P v1.4 (par PA/AIIM + pa_estadual) — o ramo 1X usa
# o MESMO schema superset, entao um enum novo sem a instrucao correspondente aqui daria
# constrained decoding com valor que o prompt nunca explica.


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
    UNIQUE (tipo, numero_normalizado)) E a esfera/UF do nó, via
    `garantis_shared...peticao_contract.ADMIN_TIPO_TO_NO`. Valor novo aqui sem entrada lá
    cai em `paf`/federal. `tests/test_enum_contrato_sink.py` cruza os dois lados.
    """

    numero: str = Field(description="Número LITERAL do processo administrativo como aparece no texto.")
    tipo: Literal["paf", "tit_sp", "pa_estadual"] = Field(
        default="paf",
        description=(
            "'paf'=processo administrativo fiscal FEDERAL (NUP/RFB, NNNNN.NNNNNN/AAAA-DD) — "
            "default; do número NÃO dá pra afirmar CARF. 'tit_sp'=AIIM/auto de infração "
            "ESTADUAL de SP (N.NNN.NNN-D). 'pa_estadual'=processo administrativo de fisco "
            "ESTADUAL (Secretaria da Fazenda de um estado; verificação fiscal, defesa/"
            "recurso administrativo) — o PROCESSO, não o auto: se o número é do AIIM use "
            "'tit_sp'. Só marque quando o texto disser o ÓRGÃO estadual; na dúvida 'paf'."
        ),
    )
    contexto: Optional[str] = Field(
        default=None, description="Snippet ~120 chars ao redor da citação (auditoria).",
    )
    par_numero: Optional[str] = Field(
        default=None,
        description=(
            "Quando o texto apresenta o PAR 'Processo Administrativo nº X (AIIM nº Y)', o "
            "número LITERAL do OUTRO item do par. Emita os DOIS como itens separados, cada "
            "um com par_numero apontando pro outro. null quando o número aparece sozinho."
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

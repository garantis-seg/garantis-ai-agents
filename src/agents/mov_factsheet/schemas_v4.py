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

from typing import Literal, Optional

from pydantic import BaseModel, Field

PROMPT_VERSION_V4 = "mov_factsheet.v4"

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
            "Inexigibilidade/nulidade da CDA/prescrição acolhida = 'procedente' (mérito), NÃO "
            "extinto_sem_merito. Use 'interlocutoria' só p/ decisão sem mérito (liminar, tutela)."
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
            "Para natureza='extinto_sem_merito': 'terminativa'=extinção processual (sem resolver "
            "mérito, ex: ilegitimidade/abandono); 'consensual'=desistência/acordo homologado; "
            "'satisfacao'=extinção por PAGAMENTO/quitação/satisfação da obrigação (art. 924 II CPC); "
            "'nenhum'/null caso contrário."
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
    valor_excluido: Optional[float] = Field(
        default=None,
        description="Em decisão PARCIAL: valor/quantia EXCLUÍDA da condenação/execução (BRL). null se n/a.",
    )
    percentual_mantido: Optional[float] = Field(
        default=None,
        description="Em decisão PARCIAL: % do crédito/pedido MANTIDO (0-100). null se n/a.",
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
            "Resumo PT-BR do que aconteceu NESTA mov. Tamanho proporcional à relevância: "
            "ato trivial = 1 frase; decisão/sentença/evento de garantia = até ~300 palavras "
            "se houver substância. Técnico-jurídico, neutro. NÃO repita o resumo do processo "
            "nem a mov anterior."
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
    data_real_ato: Optional[str] = Field(
        default=None,
        description="YYYY-MM-DD do ato real SE diferir da data de publicação. null caso contrário.",
    )

"""Prompt v4 (G10) — a LLM extrai FATOS NEUTROS de uma movimentação. FASE 2 / shadow.

Porte do contrato congelado (`~/.claude/plans/l1-fase1-contrato-2026-06-09.md`) +
`_l1_pilot/prompts_v4.py` (validado end-to-end pelo piloto zero-deploy 2026-06-09).
Coexiste com o `build_mov_factsheet_prompt` v3.1 sob flag — NÃO o substitui.

DIFERENÇA CENTRAL vs v3.1: SEM fundação-do-Tomador. A LLM não sabe (nem precisa) quem
é o cliente — ela relata QUEM está em cada polo e O QUE aconteceu, de forma neutra. O
julgamento (favorável/desfavorável) é derivado em código depois (`derivacoes.py`).

O que o prompt APOSENTA (mote — viraram código em `derivacoes`, NÃO re-introduzir aqui):
  - `<regra_polos>` inteira → `derivar_lado` / injeção-de-papel do provider.
  - `<regra_recursos>` (metade-mapeamento) → `SENTIDO_RECURSO` (recorrente × provido).
  - `<regra_extincao_sem_merito>` → `SENTIDO_EXTINCAO` (lado × motivo_extincao).
  - `<regra_titularidade>` / fundação-do-Tomador (`bloco_fundacao`) → fora do passe.
  - PR#5 Alfredo (suspensão de segurança) → `instrumento_cautelar` no `derivacoes`.

O que FICA: framing neutro · injeção seletiva de vocab por família (fiscal/trab/cível) ·
regras de EXTRAÇÃO dos 6 fatos crus novos · precisão Lei 8.437 (não rotular MS/liminar
genérica como suspensão de segurança) · taxonomia tipo_doc · rendering de docs/fallback
(reutilizado de `prompts.py` — comportamento único). Semântica por campo vive no
response_schema (`schemas_v4` descriptions).

Bloco MOV ANTERIOR: removido do caminho v4 (prompt-review Lote 1/1.3, 2026-06-10).
Prod roda paralelo sempre (`sequential_l1=False` em todos os callers) → o bloco nunca
renderizava aqui. O code-path segue vivo no v3.1 (`prompts._mov_anterior_block`) pra
pilotos sequenciais futuros. Render de prod inalterado (1A/1D byte-idêntico).
"""
from __future__ import annotations

import re
from typing import Any

from .fundacao import TAXONOMIA_TIPO_DOC
from .prompts import _summarize_doc

# ── Caps v4.4 (decisão "SEM LIMITE primeiro — qualidade > custo", 2026-06-11) ──
# Não há mais cap de 5 docs/mov nem 8k/doc: TODOS os docs entram, governados por um
# ORÇAMENTO por unidade (guarda de janela do modelo, não economia). Censo 2026-06-10:
# sem cap o input multiplica ~8,9× — custo MEDIDO e aceito pela decisão.
_V4_MOV_TEXT_CAP = 200_000        # snippet da mov (publicação pode trazer inteiro teor)
_V4_DOC_TEXT_CAP = 1_000_000      # teto por doc (janela; casa com o fetch do shared)
_V4_DOCS_BUDGET = 2_000_000       # orçamento agregado de docs por unidade (~500k tokens)
from .schemas import DocAnexado, FallbackContext, MovInput, ProcessoContext

# ── Perfil de leitura por Tipo de doc (2026-06-19) ─────────────────────────
# Resolve o timeout do L1 em docs grandes (demonstrativo de 567pg = 1,9M chars →
# Gemini 18-55s → estoura TIMEOUT_LAYER1_S=60s). NÃO é dup (memory
# digesto-ocr-text-dup = falso alarme). 2 perfis:
#   peça (substantivo: petição/sentença/acórdão/decisão...) → ler COMPLETO
#         (chunk em camada separada se >200k — follow-up; aqui mantém a janela).
#   evidência (tabular: demonstrativo/planilha/NFe/comprovante...) → HEAD+TAIL:
#         natureza+valor no cabeçalho, totais no fim, miolo = bulk por-NFe.
# Pré-classificador BARATO (sem LLM) por título/tipo/nº-páginas. Conservador:
# default 'peça'; keyword legal VENCE (uma petição grande NÃO é evidência).
_DOC_EVIDENCIA_HEAD = 50_000
_DOC_EVIDENCIA_TAIL = 30_000
_EVIDENCIA_MIN_CHARS = 200_000    # doc SEM título legal e > isto = tabular/bundle.
                                  # CHARS (não páginas): é o input do LLM que conta.
                                  # Alinha com o tamanho seguro/chunk de 200k.

_RE_DOC_PECA = re.compile(
    r"PETI[CÇ][AÃ]O|INICIAL|SENTEN[CÇ]A|AC[OÓ]RD[AÃ]O|DECIS[AÃ]O|DESPACHO|"
    r"EMBARGOS|CONTESTA[CÇ][AÃ]O|RECURSO|AGRAVO|APELA[CÇ][AÃ]O|MANIFESTA[CÇ][AÃ]O|"
    r"PARECER|VOTO|IMPUGNA[CÇ][AÃ]O|R[EÉ]PLICA|CONTRARRAZ[OÕ]ES",
    re.IGNORECASE,
)
_RE_DOC_EVIDENCIA = re.compile(
    r"DEMONSTRATIVO|PLANILHA|C[AÁ]LCULO|NOTA[S]?\s+FISCA|NF[\s\-]?E\b|COMPROVANTE|"
    r"GUIA|EXTRATO|RELA[CÇ][AÃ]O\s+DE|FICHA\s+DE\s+PONTO|SEFIP|FATURA|DARF|"
    r"\bDAS\b|MEM[OÓ]RIA\s+DE\s+C[AÁ]LCULO|DEINF",
    re.IGNORECASE,
)


def _doc_reading_profile(d: DocAnexado) -> str:
    """'peca' (ler completo) | 'evidencia' (head+tail). Conservador: default peça."""
    titulo = f"{d.titulo or ''} {d.tipo or ''}"
    if _RE_DOC_PECA.search(titulo):
        return "peca"  # peça explícita vence — petição grande NÃO é evidência
    if _RE_DOC_EVIDENCIA.search(titulo) or len(d.text_content or "") > _EVIDENCIA_MIN_CHARS:
        return "evidencia"
    return "peca"


def _evidencia_head_tail(text: str) -> str:
    """Head+tail de evidência tabular: cabeçalho (natureza+valor) + fim (totais);
    miolo por-NFe omitido com marcador explícito (no silent cap)."""
    if len(text) <= _DOC_EVIDENCIA_HEAD + _DOC_EVIDENCIA_TAIL:
        return text
    omit = len(text) - _DOC_EVIDENCIA_HEAD - _DOC_EVIDENCIA_TAIL
    return (
        text[:_DOC_EVIDENCIA_HEAD]
        + f"\n\n[... documento de EVIDÊNCIA tabular: ~{omit:,} chars do miolo "
        "omitidos (início e fim preservados — natureza/valor no cabeçalho, "
        "totais no fim) ...]\n\n"
        + text[-_DOC_EVIDENCIA_TAIL:]
    )


# Vocab por família — NEUTRO (relata as partes típicas; NÃO diz quem é "o cliente").
# Injeção seletiva: só o bloco da família da mov entra no prompt.
VOCAB_FAMILIA = {
    "fiscal": (
        "CONTEXTO FISCAL/TRIBUTÁRIO: discute exigibilidade de crédito tributário (CDA). "
        "Partes típicas: Fazenda/PGFN/Município (exequente, polo ATIVO na execução fiscal) "
        "vs contribuinte.\n"
        "- Em Execução Fiscal o contribuinte é EXECUTADO (polo passivo); em Embargos/"
        "Anulatória/MS/Repetitório ele é AUTOR (polo ativo).\n"
        "- Em EMBARGOS/ANULATÓRIA/MS (contribuinte é AUTOR): 'inexigibilidade do crédito'/"
        "'nulidade da CDA'/'prescrição' acolhida => natureza='procedente' (mérito), NÃO "
        "extinto_sem_merito.\n"
        "- EXCEÇÃO DE PRÉ-EXECUTIVIDADE (defesa DENTRO da Execução Fiscal): se ACOLHIDA "
        "extinguindo a execução => natureza='extinto_sem_merito' + motivo_extincao "
        "('terminativa' p/ prescrição/ilegitimidade) — NUNCA 'procedente' (o autor da EF é "
        "a Fazenda). Acolhimento parcial ou rejeição => natureza='interlocutoria'.\n"
        "- suspensão da exigibilidade (art. 151 CTN: depósito/parcelamento/liminar do "
        "contribuinte) => instrumento_cautelar='suspensao_exigibilidade_ctn'.\n"
        "- suspensão de SEGURANÇA (Lei 8.437, requerida pela Fazenda à presidência do "
        "tribunal) => instrumento_cautelar='suspensao_seguranca'.\n"
        "- extinção por PAGAMENTO/quitação (art. 924 II) => natureza='extinto_sem_merito', "
        "motivo_extincao='satisfacao'."
    ),
    "trabalhista": (
        "CONTEXTO TRABALHISTA: reclamante (empregado, polo ATIVO) vs reclamada (empresa, "
        "polo PASSIVO).\n"
        "- reclamação 'procedente' = pedido do empregado(autor) acolhido. Recurso ao TST => "
        "instancia='2g' (NUNCA 'stj').\n"
        "- Agravo de Petição = recurso na fase de execução. Identifique recorrente_polo pelo "
        "autor do recurso."
    ),
    "civel": (
        "CONTEXTO CÍVEL: o autor pode estar em qualquer posição — NÃO assuma lado. Apenas "
        "relate a natureza + quem recorreu (recorrente_polo) de forma neutra."
    ),
}


def _get(processo: Any, campo: str):
    """Lê de objeto (pydantic) OU dict."""
    if isinstance(processo, dict):
        return processo.get(campo)
    return getattr(processo, campo, None)


def _familia_key(processo: Any) -> str:
    """Família da mov a partir de materia + classe (viés a injetar: na dúvida → cível).

    `classe` pode vir como tree-path CNJ ("1116 - PROCESSO CÍVEL E DO TRABALHO ->
    Processo de Execução -> Execução Fiscal") — o cabeçalho contém "TRABALHO" pra
    QUALQUER classe e roteava Execução Fiscal pro vocab trabalhista (censo do
    prompt-review 2026-06-10, proc 5159436-51.2025.8.09.0051/TJGO; 'trabalh' tem
    precedência sobre 'fiscal'). Com "->" na classe, só o ÚLTIMO segmento (a classe
    folha) entra no match. `materia` não precisa: vocabulário controlado de
    apolices_monitoradas (Tributario/Trabalhista/Civel).
    """
    classe = str(_get(processo, "classe") or "")
    if "->" in classe:
        classe = classe.rsplit("->", 1)[-1]
    blob = f"{_get(processo, 'materia') or ''} {classe}".lower()
    if "trabalh" in blob or "reclamac" in blob:
        return "trabalhista"
    if "fiscal" in blob or "tribut" in blob:
        return "fiscal"
    return "civel"


def _contexto_processo_block(processo: ProcessoContext) -> str:
    """Bloco NEUTRO do processo: classe + polos + matéria. SEM resolução do Tomador."""
    pa = _get(processo, "polo_ativo") or "(vazio)"
    pp = _get(processo, "polo_passivo") or "(vazio)"
    classe = _get(processo, "classe") or "(n/d)"
    materia = _get(processo, "materia") or "(n/d)"
    return (
        "=== CONTEXTO DO PROCESSO (da base — confie nestes dados) ===\n"
        f"Classe:  {classe}\n"
        f"Matéria: {materia}\n"
        f"Polo ATIVO:   {pa}\n"
        f"Polo PASSIVO: {pp}"
    )


# Regras de EXTRAÇÃO dos 6 fatos crus novos. NEUTRAS (relatar, não julgar). O mapeamento
# fato→sentido é código (derivacoes) — NÃO descrever favorável/desfavorável aqui.
_REGRAS_CRUS = """=== REGRAS DOS CAMPOS CRUS (relate, NÃO julgue) ===
- tem_decisao: true SÓ com decisão material. Expediente/intimação/juntada/penhora-online/
  vista/conclusão/processamento de recurso = false (e então natureza/recorrente/provido/
  resultado_interlocutorio = null). Penhora online NÃO é decisão de mérito.
- recorrente_polo + provido: SÓ em decisão de RECURSO. Leia no texto QUEM recorreu (apelante/
  agravante/recorrente), ache em qual polo ele está ('ativo'/'passivo'), e o resultado
  (provido/negado/parcial/não-conhecido). Se não der pra identificar o recorrente =>
  recorrente_polo=null. NÃO diga se foi bom/ruim pra alguém.
- instrumento_cautelar: marque 'suspensao_seguranca' SÓ se for o incidente da Lei 8.437/12.016
  (requerido pelo ENTE PÚBLICO à PRESIDÊNCIA do tribunal pra sustar liminar). Liminar/MS comum
  => null. Precisão aqui é crítica. NÃO marque instrumento_cautelar numa SENTENÇA FINAL
  (procedente/improcedente) — instrumento é de decisão incidental/interlocutória.
- resultado_interlocutorio + requerente_polo: SÓ para TUTELA/LIMINAR/medida cautelar SUBSTANTIVA.
  Diga se foi 'deferida'/'indeferida' E qual polo PEDIU (requerente_polo='ativo'/'passivo').
  ⚠ NÃO preencha para DESPACHO DE IMPULSO: 'deferir a inicial', 'determinar citação', 'deferir
  penhora/penhora online', 'conceder prazo' são ANDAMENTO PROCEDIMENTAL (não tutela) =>
  resultado_interlocutorio=null, requerente_polo=null.
- motivo_extincao: PREENCHA SÓ quando natureza='extinto_sem_merito'. Sentença de mérito
  (procedente/improcedente) => motivo_extincao=null. 'satisfacao' EXIGE texto explícito de
  PAGAMENTO/QUITAÇÃO/satisfação da obrigação (art. 924 II) — mero 'arquivamento'/'baixa'/
  'prejudicado' NÃO é satisfacao.
- efeito_suspensivo: true se o recurso/decisão suspende os efeitos da decisão recorrida.
- evento_garantia.tipo='acionamento' = ordem de EXECUTAR/converter a garantia em pagamento
  (intime-se a garantidora a pagar/depositar). Distinga de 'levantamento' (restituição da
  garantia AO depositante)."""


def _build_orfao_prompt_v4(
    processo: ProcessoContext,
    mov: MovInput,
    documentos_anexados: list[DocAnexado],
) -> str:
    """Prompt NEUTRO pro ramo DOCUMENTO (classe 1D) — doc analisado isoladamente, sem
    movimento vinculado ("avulso"; ex-"órfão").

    Saída = MovFactSheetCardV4 (mesmo schema). natureza de_fluxo/acessorio entra como
    RACIOCÍNIO (orienta data + se há decisão), não como campo. SEM fundação-do-Tomador.
    v4.3 (#2 prompt-review): ganha VOCAB_FAMILIA + _REGRAS_CRUS (um doc pode ser uma
    sentença — precisa das mesmas regras de extração do ramo movimento) + metadata do
    doc (censo 2026-06-11: metadata jusbrasil é 100% preenchida e o título identifica
    a peça — ex: 'PETICAO INICIAL').
    """
    doc = documentos_anexados[0] if documentos_anexados else None
    txt = (doc.text_content or "").strip() if doc else ""
    if not txt:
        txt = (mov.texto or "").strip()

    meta_bits = []
    if doc:
        if doc.tipo:
            meta_bits.append(f"tipo: {doc.tipo}")
        if doc.titulo:
            meta_bits.append(f"titulo: {doc.titulo}")
        if doc.data_documento:
            meta_bits.append(f"data_documento: {doc.data_documento}")
        if doc.provider:
            meta_bits.append(f"fonte: {doc.provider}")
    meta_line = ("\n  " + " | ".join(meta_bits)) if meta_bits else ""

    fam = _familia_key(processo)

    return f"""Você é um extrator de FATOS NEUTROS de documentos judiciais brasileiros.
RELATE objetivamente o que o documento contém — NÃO julgue se algo é bom ou ruim para
alguém. A composição dos polos já vem pronta no CONTEXTO DO PROCESSO abaixo; identifique
em QUAL POLO ('ativo' ou 'passivo') está cada ator citado no texto. O julgamento é feito
por outro sistema.

Este é um DOCUMENTO AVULSO — analisado isoladamente, sem movimento processual vinculado.
Classifique-o e produza o FactSheet (mesmo schema dos demais).

RACIOCÍNIO sobre a NATUREZA do documento (orienta data e se há decisão):
- PEÇA DESTE PROCESSO ('de_fluxo'): tem ato/momento processual próprio nestes autos
  (petição, decisão, sentença, despacho, acórdão, certidão deste juízo). Tem data própria.
- ANEXO ('acessorio'): juntado como prova/instrução, SEM ato próprio nestes autos
  (contrato, apólice, procuração, nota fiscal, guia). Se o documento CLARAMENTE pertence a
  OUTRO órgão/rito (PROCON, INSS, Receita, junta comercial) — é 'acessorio', MESMO com forma
  de ato. Só é 'de_fluxo' o produzido DENTRO deste processo judicial.
- Para 'acessorio'/documento de fora: tem_decisao=false. Para 'de_fluxo' que SEJA peça
  decisória (sentença/decisão/acórdão deste processo): tem_decisao pode ser true + os fatos
  neutros (natureza/recorrente_polo/provido…) que o texto sustentar.

{_contexto_processo_block(processo)}

{VOCAB_FAMILIA[fam]}

{TAXONOMIA_TIPO_DOC}

{_REGRAS_CRUS}

=== DOCUMENTO (id {mov.mov_id}) ==={meta_line}
{txt[:_V4_DOC_TEXT_CAP]}

Extraia os fatos neutros no schema MovFactSheetCardV4. Preencha SÓ o que o texto sustenta;
o resto null."""


# Guarda de janela do ramo petição (peticao_extract.v1): petições reais têm 100k+ chars
# e os conectores (CDA em planilha, citações) podem estar em qualquer ponto — cap alto
# alinhado à decisão "sem limite primeiro, qualidade > custo" (2026-06-11), limitado só
# pela janela do flash-lite (1M tokens ≈ 4M chars; 200k chars ≈ 50k tokens, cobre p99).
_PETICAO_TEXT_CAP_CHARS = 200_000


def _build_peticao_prompt_v4(
    processo: ProcessoContext,
    mov: MovInput,
    documentos_anexados: list[DocAnexado],
) -> str:
    """Prompt do ramo PETIÇÃO INICIAL (peticao_extract.v1) — FASE 4 conexos.

    Diferenças vs o ramo DOCUMENTO: contexto AFIRMATIVO (a integração já identificou
    que ESTE doc é a petição inicial — identify_peticao_doc metadata-first) + extração
    DIRIGIDA dos conectores (cdas + processos_citados com papel), conforme o contrato
    `prompts/fase4-alfredo-handoff-peticao-extraction.md`. Escopo = SÓ petição inicial:
    fora dela a precisão das citações despenca (validação Onda 1).

    PROMPT v0 (esqueleto) — as regras jurídicas de `papel` são DS do Alfredo; iterar
    aqui + mini-eval de petições rotuladas antes de plugar no sink.
    """
    doc = documentos_anexados[0] if documentos_anexados else None
    txt = (doc.text_content or "").strip() if doc else ""
    if not txt:
        txt = (mov.texto or "").strip()

    meta_bits = []
    if doc:
        if doc.titulo:
            meta_bits.append(f"titulo: {doc.titulo}")
        if doc.data_documento:
            meta_bits.append(f"data_documento: {doc.data_documento}")
        if doc.provider:
            meta_bits.append(f"fonte: {doc.provider}")
    meta_line = ("\n  " + " | ".join(meta_bits)) if meta_bits else ""

    fam = _familia_key(processo)

    return f"""Você é um extrator de FATOS NEUTROS de peças judiciais brasileiras.
RELATE objetivamente — NÃO julgue se algo é bom ou ruim para alguém. A composição dos
polos já vem pronta no CONTEXTO DO PROCESSO abaixo. O julgamento é feito por outro sistema.

Este documento É a PETIÇÃO INICIAL deste processo (já identificada pela integração —
confie nisso). Sua missão tem DUAS partes:

PARTE 1 — FactSheet da peça (campos do card):
- tipo_doc='peticao_inicial'. tem_decisao=false e decisao toda null (petição é pedido da
  parte, não decisão judicial).
- resumo_ato: a TESE e o PEDIDO da inicial em até ~150 palavras (quem pede, o quê, com
  que fundamento principal).
- evento_garantia: SÓ se a petição OFERECE garantia (seguro garantia/fiança/depósito) —
  tipo='apresentacao' + subtipo. Senão 'nenhum'.
- valores: valor_debito_executado/valor_garantia quando explícitos.

PARTE 2 — EXTRAÇÃO DIRIGIDA dos CONECTORES (o motivo deste passe):
- cdas[]: TODOS os números de CDA/inscrição em dívida ativa que ESTE processo executa ou
  discute (corpo da petição E planilhas/listas anexas ao texto), ESCRITOS no documento.
  Número LITERAL como está no texto + ente/tributo/valor quando explícitos. NÃO normalize
  o número. Artigo de lei NÃO é CDA.
- processos_citados[]: SÓ números de PROCESSO JUDICIAL no formato CNJ
  (NNNNNNN-DD.AAAA.J.TR.OOOO, ou 20 dígitos contínuos) que estejam ESCRITOS no
  documento. NÃO são processos: artigos de lei (CF/CPC/CTN), números de lei ou LC
  (ex: Lei 12.016, LC 190/22), súmulas, e registros de tribunal superior fora do
  formato CNJ (RE/AREsp/ADI + número curto). NUNCA extraia números mencionados
  NESTAS INSTRUÇÕES — só o que está no documento. Campo crítico `papel`:
  · 'originario' — o contexto indica o processo de ORIGEM desta ação: 'distribuição por
    dependência', 'Processo de Origem', 'processo originário', 'nos autos da Execução
    Fiscal nº', 'em apenso a'. É o sinal de ouro — só marque com GATILHO TEXTUAL claro.
    Processo PARADIGMA / prova emprestada / caso de outro autor citado como exemplo NÃO
    é originário (mesmo que envolva a mesma empresa) => 'jurisprudencia' ou 'incerto'.
  · 'jurisprudencia' — CNJ dentro de ementa/precedente citado (assinaturas: 'Rel. Des.',
    'Relator:', 'Data de Julgamento', Turma/Câmara, sufixo de 2ª instância).
  · 'derivado'/'incidente' — outra ação derivada/incidental LIGADA A ESTE processo,
    envolvendo a MESMA empresa/parte privada (a parte pública pode variar: Fazenda,
    autoridade coatora, ente). Se o contexto mostra caso de OUTRA empresa/parte citado
    como exemplo ou precedente, NÃO é derivado => 'jurisprudencia' (se em ementa) ou
    'incerto'.
  · 'incerto' — não dá pra classificar com segurança (a integração decide depois com
    dados que você não tem — na dúvida, prefira 'incerto' a chutar papel relacional).
  Em TODOS: copie ~120 chars de contexto ao redor da citação (campo `contexto`).
  NÃO converta números incompletos pra 20 dígitos: se o número no documento não está
  no formato CNJ completo (RE/AREsp/ADI/registros curtos), NÃO o estique — ignore.
- NÃO deduza direção do par (quem é mais novo/velho) — a integração resolve por data.
- confianca_extracao: 0-1 sobre a EXTRAÇÃO dos conectores (texto limpo=alta; OCR
  ruidoso/citações ambíguas=baixa).

{_contexto_processo_block(processo)}

{VOCAB_FAMILIA[fam]}

=== PETIÇÃO INICIAL (id {mov.mov_id}) ==={meta_line}
{txt[:_PETICAO_TEXT_CAP_CHARS]}

Extraia no schema PeticaoExtractCardV4. Preencha SÓ o que o texto sustenta; o resto null."""


def _build_doc_incerto_prompt_v4(
    processo: ProcessoContext,
    mov: MovInput,
    documentos_anexados: list[DocAnexado],
) -> str:
    """Prompt do ramo 1X (doc_incerto_extract.v1) — doc de tipo NÃO identificado.

    Variante do 1P pro fallback do identify (camada L3 — doc substancial do 1º
    dia da captura, sem confirmação de tipo): frame de INCERTEZA + classificação
    ativa via TAXONOMIA completa (do ramo 1D) + a MESMA extração relacional do
    1P com papel MAIS conservador (default jurisprudência/incerto em peça
    decisória — decisões citam precedente o tempo todo). Censo 2026-06-12: a
    regra crua do 1º dia tinha 0/15 precisão de identify; aqui a incerteza vai
    pra prompt e a extração degrada com graça. Schema REUSA PeticaoExtractCardV4
    (já tem tipo_doc). Draft aprovado Elton 2026-06-12
    (~/.claude/plans/ramo-1x-doc-incerto-draft-2026-06-12.md).
    """
    doc = documentos_anexados[0] if documentos_anexados else None
    txt = (doc.text_content or "").strip() if doc else ""
    if not txt:
        txt = (mov.texto or "").strip()

    meta_bits = []
    if doc:
        if doc.tipo:
            meta_bits.append(f"tipo: {doc.tipo}")
        if doc.titulo:
            meta_bits.append(f"titulo: {doc.titulo}")
        if doc.data_documento:
            meta_bits.append(f"data_documento: {doc.data_documento}")
        if doc.provider:
            meta_bits.append(f"fonte: {doc.provider}")
    meta_line = ("\n  " + " | ".join(meta_bits)) if meta_bits else ""

    fam = _familia_key(processo)

    return f"""Você é um extrator de FATOS NEUTROS de documentos judiciais brasileiros.
RELATE objetivamente — NÃO julgue se algo é bom ou ruim para alguém. A composição dos
polos já vem pronta no CONTEXTO DO PROCESSO abaixo. O julgamento é feito por outro sistema.

A integração NÃO conseguiu identificar o TIPO deste documento. Ele foi selecionado por
ser um documento substancial do primeiro dia disponível da captura — PODE ser a petição
inicial, mas pode ser decisão, sentença, despacho, certidão, manifestação ou um anexo.
NÃO assuma que é a petição inicial. Sua missão tem DUAS partes:

PARTE 1 — CLASSIFICAR e produzir o FactSheet:
- tipo_doc: classifique pelo CONTEÚDO usando a TAXONOMIA COMPLETA abaixo (a mesma dos
  demais ramos — não há lista resumida aqui). Atenção à distinção mais traiçoeira deste
  ramo: 'peticao_inicial' (inaugura a ação) × 'peticao' (manifestação intercorrente) —
  só marque inicial com os 4 sinais: endereçamento ao juízo + qualificação das partes +
  causa de pedir + pedidos.
- RACIOCÍNIO sobre a NATUREZA (orienta data e se há decisão):
  · PEÇA DESTE PROCESSO ('de_fluxo'): tem ato/momento processual próprio nestes autos.
  · ANEXO ('acessorio'): juntado como prova/instrução, sem ato próprio nestes autos. Se
    pertence a OUTRO órgão/rito (PROCON, INSS, Receita) é 'acessorio' mesmo com forma de ato.
- Petição (inicial ou não) e 'acessorio': tem_decisao=false e decisao toda null. Peça
  decisória DESTE processo (sentença/decisão/acórdão): tem_decisao pode ser true + os
  fatos neutros que o texto sustentar (mesmas regras de extração do ramo movimento).
- resumo_ato: o que o documento É e o que contém, em até ~150 palavras.
- evento_garantia: SÓ se o documento OFERECE/JUNTA garantia (seguro garantia/fiança/
  depósito) — tipo + subtipo. Senão 'nenhum'.
- valores: valor_debito_executado/valor_garantia quando explícitos.

PARTE 2 — EXTRAÇÃO DIRIGIDA dos CONECTORES (independe do tipo classificado):
- cdas[]: TODOS os números de CDA/inscrição em dívida ativa que ESTE processo executa ou
  discute (corpo E planilhas/listas), ESCRITOS no documento. Número LITERAL + ente/
  tributo/valor quando explícitos. NÃO normalize. Artigo de lei NÃO é CDA.
- processos_citados[]: SÓ números de PROCESSO JUDICIAL no formato CNJ
  (NNNNNNN-DD.AAAA.J.TR.OOOO, ou 20 dígitos contínuos) ESCRITOS no documento. NÃO são
  processos: artigos de lei, números de lei/LC, súmulas, registros fora do formato CNJ
  (RE/AREsp/ADI + número curto). NUNCA extraia números mencionados NESTAS INSTRUÇÕES.
  Campo crítico `papel` — ATENÇÃO REDOBRADA aqui: como o tipo do documento é incerto,
  citações têm probabilidade MAIOR de ser jurisprudência/referência (decisões e
  sentenças citam precedentes o tempo todo):
  · 'originario' — SÓ com gatilho textual explícito: 'distribuição por dependência',
    'Processo de Origem', 'processo originário', 'nos autos da Execução Fiscal nº',
    'em apenso a'. Paradigma/prova emprestada/caso de outro autor NÃO é originário.
  · 'jurisprudencia' — CNJ dentro de ementa/precedente ('Rel. Des.', 'Relator:',
    'Data de Julgamento', Turma/Câmara). Em peça DECISÓRIA, o default de uma citação
    sem gatilho claro é jurisprudência ou 'incerto' — nunca 'derivado'.
  · 'derivado'/'incidente' — outra ação LIGADA A ESTE processo, da MESMA empresa/parte
    privada (a parte pública pode variar). Exige contexto explícito de ligação.
  · 'incerto' — na dúvida, SEMPRE prefira 'incerto' a chutar papel relacional.
  Em TODOS: copie ~120 chars de contexto ao redor da citação (campo `contexto`).
  NÃO converta números incompletos pra 20 dígitos — se não está no formato CNJ
  completo, ignore.
- NÃO deduza direção do par — a integração resolve por data.
- confianca_extracao: 0-1 sobre a EXTRAÇÃO dos conectores. Documento de tipo incerto
  ou OCR ruidoso => comece de 0.7 pra baixo.

{_contexto_processo_block(processo)}

{VOCAB_FAMILIA[fam]}

{TAXONOMIA_TIPO_DOC}

{_REGRAS_CRUS}

=== DOCUMENTO DE TIPO NÃO IDENTIFICADO (id {mov.mov_id}) ==={meta_line}
{txt[:_PETICAO_TEXT_CAP_CHARS]}

Extraia no schema PeticaoExtractCardV4. Preencha SÓ o que o texto sustenta; o resto null."""


def build_mov_factsheet_prompt_v4(
    processo: ProcessoContext,
    mov: MovInput,
    documentos_anexados: list[DocAnexado] | None = None,
    fallback_context: FallbackContext | None = None,
    classe: str | None = None,
) -> str:
    """Prompt v4 (fatos neutros) pra extrair o FactSheet de UMA movimentação.

    Drop-in da assinatura de `build_mov_factsheet_prompt` (v3.1) — o agente troca a função
    sob flag. classe '1D' = ramo DOCUMENTO (doc avulso); classe 'peticao' = ramo PETIÇÃO
    INICIAL (peticao_extract.v1, opt-in do caller — prod nunca envia hoje).
    """
    documentos_anexados = documentos_anexados or []

    if classe == "peticao":
        return _build_peticao_prompt_v4(processo, mov, documentos_anexados)

    if classe == "doc_incerto":
        return _build_doc_incerto_prompt_v4(processo, mov, documentos_anexados)

    if classe == "1D":
        return _build_orfao_prompt_v4(processo, mov, documentos_anexados)

    fam = _familia_key(processo)

    # Docs anexados (v4.4 sem-limite): TODOS os docs, sob orçamento agregado por
    # unidade. O doc que estoura o restante é truncado; excedentes viram marcador
    # explícito (no silent caps).
    has_docs = len(documentos_anexados) > 0
    if has_docs:
        blocks: list[str] = []
        remaining = _V4_DOCS_BUDGET
        rendered = 0
        total = len(documentos_anexados)
        for i, d in enumerate(documentos_anexados):
            if remaining <= 0:
                break
            # Perfil de leitura: evidência tabular → head+tail; peça → completo.
            raw = (d.text_content or "").strip()
            eff_text = (
                _evidencia_head_tail(raw)
                if _doc_reading_profile(d) == "evidencia" else raw
            )
            cap = min(_V4_DOC_TEXT_CAP, remaining)
            block = _summarize_doc(d, i, total, text_cap=cap, text_override=eff_text)
            remaining -= min(len(eff_text), cap)
            blocks.append(block)
            rendered += 1
        docs_block = "\n\n".join(blocks)
        if rendered < total:
            docs_block += (
                f"\n\n[+ {total - rendered} docs omitidos — orçamento de janela do modelo]"
            )
        docs_section = (
            f"\n\n=== DOCUMENTOS ANEXADOS A ESTA MOV ({total} doc(s)) ===\n{docs_block}"
        )
    else:
        docs_section = ""

    # RESUMO DO PROCESSO removido do caminho v4 (decisão D do prompt-review,
    # 2026-06-11): a dependência (resumo_ia via Escavador lazy_gen) não é garantida
    # em todo processo, e o bloco era contexto de FUNDO, não desta mov. Se a
    # qualidade dos 1A degradar, re-adicionar é a melhoria futura (rollback =
    # revert deste commit). O lazy_gen upstream NÃO foi tocado (resumo_ia tem
    # consumidores fora da L1).

    # Instruções de uso do contexto — neutras (docs prevalecem; não copie).
    instrucoes = []
    if has_docs:
        instrucoes.append(
            "- A informação SUBSTANTIVA está nos DOCUMENTOS ANEXADOS — use o conteúdo deles "
            "pra preencher decisao/valores/evento_garantia.\n"
            "- resumo_ato sintetiza O QUE ESTÁ NESTA MOV (incl. os docs), NÃO copia o resumo do "
            "processo."
        )
    else:
        instrucoes.append(
            "- Sem doc anexo, você SÓ tem o snippet da publicação + metadata. NÃO INVENTE "
            "conteúdo. Snippet genérico (ex: 'Expedição de outros documentos', 'Juntada de "
            "petição') => relevancia_merito='ruido'/'baixa' + tem_decisao=false."
        )
    contexto_extra = (
        "\n\n=== INSTRUÇÕES PARA USO DO CONTEXTO ===\n" + "\n".join(instrucoes) if instrucoes else ""
    )

    texto = (mov.texto or "").strip()
    if len(texto) > _V4_MOV_TEXT_CAP:
        texto = texto[:_V4_MOV_TEXT_CAP] + "..."

    mov_meta = [f"id: {mov.mov_id}"]
    if mov.data:
        mov_meta.append(f"data: {mov.data}")
    if mov.tipo:
        mov_meta.append(f"tipo_origem: {mov.tipo}")
    mov_meta_s = "\n  ".join(mov_meta)

    return f"""Você é um extrator de FATOS NEUTROS de movimentações judiciais brasileiras.
Sua tarefa NÃO é julgar se algo é bom ou ruim para alguém — é RELATAR objetivamente o que
aconteceu. A composição dos polos já vem pronta no CONTEXTO DO PROCESSO abaixo; o seu
trabalho é identificar em QUAL POLO está cada ator citado no texto ('o agravante',
'o requerente', 'a executada' → 'ativo' ou 'passivo'). O julgamento é feito por outro
sistema.

REGRA DE OURO: emita fatos NEUTROS. NÃO escreva 'favorável'/'desfavorável'. Para recursos,
resolva QUAL POLO recorreu usando o CONTEXTO DO PROCESSO (recorrente_polo='ativo' ou
'passivo') e diga se foi provido — nunca relativo a 'cliente'/'parte'. Você não sabe quem
é o cliente.

{_contexto_processo_block(processo)}

{VOCAB_FAMILIA[fam]}

{TAXONOMIA_TIPO_DOC}

{_REGRAS_CRUS}

=== MOVIMENTAÇÃO ===
  {mov_meta_s}

  texto da publicação (snippet):
  {texto}{docs_section}{contexto_extra}

Extraia os fatos neutros no schema MovFactSheetCardV4. Preencha SÓ o que o texto sustenta;
o resto null."""

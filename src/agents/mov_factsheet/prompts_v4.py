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

from typing import Any

from .fundacao import TAXONOMIA_TIPO_DOC
from .prompts import (
    _DOC_LIST_CAP,
    _summarize_doc,
)
from .schemas import DocAnexado, FallbackContext, MovInput, ProcessoContext


# Vocab por família — NEUTRO (relata as partes típicas; NÃO diz quem é "o cliente").
# Injeção seletiva: só o bloco da família da mov entra no prompt.
VOCAB_FAMILIA = {
    "fiscal": (
        "CONTEXTO FISCAL/TRIBUTÁRIO: discute exigibilidade de crédito tributário (CDA). "
        "Partes típicas: Fazenda/PGFN/Município (exequente, polo ATIVO na execução fiscal) "
        "vs contribuinte.\n"
        "- Em Execução Fiscal o contribuinte é EXECUTADO (polo passivo); em Embargos/"
        "Anulatória/MS/Repetitório ele é AUTOR (polo ativo).\n"
        "- 'inexigibilidade do crédito'/'nulidade da CDA'/'prescrição' acolhida => "
        "natureza='procedente' (mérito), NÃO extinto_sem_merito.\n"
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
    """Prompt NEUTRO pro DOCUMENTO ÓRFÃO (classe 1D) — doc sem ato processual vinculado.

    Saída = MovFactSheetCardV4 (mesmo schema). natureza de_fluxo/acessorio entra como
    RACIOCÍNIO (orienta data + se há decisão), não como campo. SEM fundação-do-Tomador.
    """
    txt = ""
    if documentos_anexados:
        txt = (documentos_anexados[0].text_content or "").strip()
    if not txt:
        txt = (mov.texto or "").strip()
    return f"""Você é um extrator de FATOS NEUTROS de documentos judiciais brasileiros.
RELATE objetivamente o que o documento contém — NÃO julgue se algo é bom ou ruim para
alguém. A composição dos polos já vem pronta no CONTEXTO DO PROCESSO abaixo; identifique
em QUAL POLO ('ativo' ou 'passivo') está cada ator citado no texto. O julgamento é feito
por outro sistema.

Este é um DOCUMENTO ÓRFÃO — NÃO vinculado a um movimento processual. Classifique-o e
produza o FactSheet (mesmo schema dos demais).

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

{TAXONOMIA_TIPO_DOC}

=== DOCUMENTO ÓRFÃO (id {mov.mov_id}) ===
{txt[:8000]}

Extraia os fatos neutros no schema MovFactSheetCardV4. Preencha SÓ o que o texto sustenta;
o resto null."""


def build_mov_factsheet_prompt_v4(
    processo: ProcessoContext,
    mov: MovInput,
    documentos_anexados: list[DocAnexado] | None = None,
    fallback_context: FallbackContext | None = None,
    classe: str | None = None,
) -> str:
    """Prompt v4 (fatos neutros) pra extrair o FactSheet de UMA movimentação.

    Drop-in da assinatura de `build_mov_factsheet_prompt` (v3.1) — o agente troca a função
    sob flag. classe '1D' = documento órfão (ramo neutro próprio).
    """
    documentos_anexados = documentos_anexados or []

    if classe == "1D":
        return _build_orfao_prompt_v4(processo, mov, documentos_anexados)

    fam = _familia_key(processo)

    # Docs anexados (reusa o rendering de prompts.py — cap 8000/doc, _DOC_LIST_CAP docs).
    has_docs = len(documentos_anexados) > 0
    if has_docs:
        docs_capped = documentos_anexados[:_DOC_LIST_CAP]
        docs_block = "\n\n".join(
            _summarize_doc(d, i, len(docs_capped)) for i, d in enumerate(docs_capped)
        )
        if len(documentos_anexados) > _DOC_LIST_CAP:
            docs_block += f"\n\n[+ {len(documentos_anexados) - _DOC_LIST_CAP} docs omitidos do prompt]"
        docs_section = (
            f"\n\n=== DOCUMENTOS ANEXADOS A ESTA MOV ({len(documentos_anexados)} doc(s)) ===\n{docs_block}"
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
    if len(texto) > 3000:
        texto = texto[:3000] + "..."

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

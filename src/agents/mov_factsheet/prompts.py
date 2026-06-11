"""Prompt pro mov_factsheet agent (engine v6_meritos camada 1).

REV2 2026-05-20 PM: doc-text first-class. Quando documentos_anexados nao
vazio, LLM le o texto do doc junto. Quando vazio, fallback formal com
processo summary + mov anterior.

REV3 2026-05-25 (piloto sequencial L1): fb_ctx pode ser passado SEMPRE
quando caller esta em modo cadenciado, mesmo com docs. Nesse caso o
prompt acrescenta bloco CONTEXTO ANTERIOR com instrucoes narrowadas
(uso so pra resolver pronouns/refs, docs prevalecem sobre contexto).
Memory: engine-v6-piloto-sequencial-l1-2026-05-25.

REV4 2026-05-25 (P1 do prompt-engineering FINDINGS):
Removido bloco "=== FORMATO DE SAIDA ===" (~50 linhas duplicando shape JSON).
Output JSON ja eh enforced via response_schema=MovFactSheetCard em agent.py
(Gemini structured output nativo). Semantica de cada campo agora vive em
Field(description=...) no schemas.py. PROMPT_VERSION bumped pra v2.0.

REV5 2026-05-25 (P2 do prompt-engineering FINDINGS):
REGRA DE LEITURA DE POLOS + REGRA RECURSOS + REGRA EXTINCAO SEM MERITO movidas
do meio do prompt pro TOPO em bloco <regras_criticas>...</regras_criticas>.
Motivacao: Lost-in-the-Middle (Liu 2023 + MIT 2025) — info critica no meio do
prompt eh ignorada >30% das vezes. Google recomenda regras no topo + restate
no fim. <lembrete_final> adicionado no fim como recency anchor. PROMPT_VERSION
bumped pra v2.1.
"""

from .schemas import DocAnexado, FallbackContext, MovInput, ProcessoContext
from .fundacao import (
    MODULO_TRABALHISTA,
    REGRA_TITULARIDADE,
    RELEVANTE_GARANTIA,
    TAXONOMIA_TIPO_DOC,
    TRAVA_DECISAO,
    bloco_fundacao,
    eh_trabalhista,
    familia_block,
)


# Cap por doc anexado no prompt (Flash Lite 1M context aguenta, mas economiza)
_DOC_TEXT_CAP_CHARS = 8000
_DOC_LIST_CAP = 5  # max docs anexados por mov
_RESUMO_PROCESSO_CAP = 1000


def _summarize_doc(doc: DocAnexado, idx: int, total: int, text_cap: int = _DOC_TEXT_CAP_CHARS) -> str:
    """Bloco de 1 doc no prompt. text_cap: cap de exibição POR VERSÃO — default 8.000
    preserva o v3.1 congelado; o v4.4+ passa o próprio orçamento (sem-limite)."""
    text = (doc.text_content or "").strip()
    truncated_note = ""
    if len(text) > text_cap:
        text = text[:text_cap]
        truncated_note = f"\n  [TRUNCADO a {text_cap} chars do original]"
    parts = [f"--- DOC {idx + 1}/{total} ---"]
    meta = []
    if doc.tipo:
        meta.append(f"tipo: {doc.tipo}")
    if doc.titulo:
        meta.append(f"titulo: {doc.titulo}")
    if doc.data_documento:
        meta.append(f"data_documento: {doc.data_documento}")
    if doc.paginas:
        meta.append(f"paginas: {doc.paginas}")
    if doc.provider:
        meta.append(f"provider: {doc.provider}")
    if meta:
        parts.append("  " + " | ".join(meta))
    parts.append("  texto:")
    parts.append("  " + text.replace("\n", "\n  "))
    if truncated_note:
        parts.append(truncated_note)
    return "\n".join(parts)


def _processo_resumo_block(ctx: FallbackContext | None) -> str:
    """Bloco RESUMO DO PROCESSO (so o resumo_ia, sem MOV ANTERIOR)."""
    if not ctx or not ctx.processo_resumo_ia:
        return ""
    resumo = ctx.processo_resumo_ia[:_RESUMO_PROCESSO_CAP]
    return (
        f"\n\n=== RESUMO DO PROCESSO (cascata IA, cap {_RESUMO_PROCESSO_CAP} chars) ===\n"
        f"{resumo}"
    )


def _mov_anterior_block(ctx: FallbackContext | None) -> str:
    """Bloco MOV ANTERIOR (so quando ha resumo_ato anterior — modo cadenciado)."""
    if not ctx or not ctx.mov_anterior_resumo:
        return ""
    prev_cat = ctx.mov_anterior_categoria or "?"
    prev_dist = (
        f"ha {ctx.distance_dias_mov_anterior} dias atras"
        if ctx.distance_dias_mov_anterior is not None
        else "data anterior nao informada"
    )
    return (
        f"\n\n=== MOV ANTERIOR NA TIMELINE (categoria={prev_cat}, {prev_dist}) ===\n"
        f"{(ctx.mov_anterior_resumo or '')[:600]}"
    )


def _build_orfao_prompt(
    processo: ProcessoContext,
    mov: MovInput,
    documentos_anexados: list[DocAnexado],
) -> str:
    """Prompt pro DOCUMENTO ÓRFÃO (classe 1D) — doc sem ato processual vinculado.

    Saída = MovFactSheetCard (mesmo schema; sem OrphanDocCard separado). O conceito
    natureza de_fluxo/acessorio entra como RACIOCÍNIO (orienta a data e se há
    decisão), não como campo. resumo vai em resumo_ato; tem_decisao=false salvo se
    o doc for uma peça decisória. Porte do POC l1_comum._build_orfao."""
    # o texto do órfão vem como o 1º doc anexado (o shared monta assim) ou no texto da mov
    txt = ""
    if documentos_anexados:
        txt = (documentos_anexados[0].text_content or "").strip()
    if not txt:
        txt = (mov.texto or "").strip()
    trunc = "\n  [TRUNCADO]" if len(txt) > _DOC_TEXT_CAP_CHARS else ""
    txt = txt[:_DOC_TEXT_CAP_CHARS].replace("\n", "\n  ")

    return f"""Voce e analista juridico-securitario brasileiro especializado em SEGURO GARANTIA JUDICIAL.

Este e um DOCUMENTO ORFAO — NAO vinculado a nenhum movimento processual. Classifique-o
e produza o FactSheet (mesmo schema dos demais).

RACIOCINIO sobre a NATUREZA do documento (orienta data e se ha decisao):
- PECA DESTE PROCESSO ('de_fluxo'): tem ato/momento processual proprio nestes autos
  (peticao, decisao, sentenca, despacho, acordao, certidao deste juizo). Tem data
  processual propria.
- ANEXO ('acessorio'): juntado como prova/instrucao, SEM ato proprio nestes autos
  (contrato, apolice, procuracao, nota fiscal, guia, situacao cadastral). PRINCIPIO
  FIRME: se o documento CLARAMENTE pertence a OUTRO orgao/autarquia/rito (PROCON,
  INSS, Receita, junta comercial, agencia reguladora) — e 'acessorio', MESMO com
  forma de ato (ata, oficio, decisao administrativa). So e 'de_fluxo' o produzido
  DENTRO deste processo judicial.
- Para 'acessorio' / documento de fora: tem_decisao=FALSE (nao e decisao DESTE juizo).
  Para 'de_fluxo' que SEJA peca decisoria (sentenca/decisao/acordao deste processo):
  tem_decisao pode ser true, com sentido pela fundacao abaixo.

{('=== CONTEXTO DA GARANTIA ===' + chr(10) + bloco_fundacao(processo) + familia_block(processo))}

=== DOCUMENTO ORFAO ===
  id: {mov.mov_id}
  texto:
  {txt}{trunc}

=== CLASSIFICACAO ===
{TAXONOMIA_TIPO_DOC}

{RELEVANTE_GARANTIA}

=== CAMPOS A EMITIR (MovFactSheetCard) ===
- resumo_ato: resumo fiel PT-BR ACENTUADO, TAMANHO PROPORCIONAL A RELEVANCIA (doc
  trivial/acessorio = poucas palavras; peca decisoria/apolice/prova central = ate
  ~400 palavras). Teto e ESPACO, nao meta. A analise seguinte so vera este resumo.
- tipo_doc: um dos valores da taxonomia acima.
- relevante_garantia: bool (ver regra acima).
- relevancia_merito: alta|media|baixa|ruido.
- decisao.tem_decisao: false p/ acessorio/anexo; true SO se o doc e peca decisoria
  DESTE processo (entao preencha sentido pela fundacao; senao sentido/instancia/
  natureza = null).
- evento_garantia: se o doc e apolice/fianca/deposito/recusa, preencha tipo; senao 'nenhum'.
- data_real_ato: data do ato/protocolo SE explicita no texto (YYYY-MM-DD); null se nao.
- confianca: 0-1.

EXCECAO de idioma: valores de ENUM (tipo_doc, sentido, etc.) sao ASCII, nunca
acentuados. So o texto livre (resumo_ato) leva acento.

Output: JSON conforme schema MovFactSheetCard (enforced via response_schema do Gemini).
Echo de mov_id deste input.
"""


def build_mov_factsheet_prompt(
    processo: ProcessoContext,
    mov: MovInput,
    documentos_anexados: list[DocAnexado] | None = None,
    fallback_context: FallbackContext | None = None,
    classe: str | None = None,
) -> str:
    """Single-step prompt pra extrair o FactSheet de UMA movimentacao.

    Quando documentos_anexados nao vazio: bloco DOCUMENTOS ANEXADOS no prompt,
    LLM le o doc text. Quando vazio: bloco FALLBACK CONTEXT com processo summary
    + mov anterior, LLM processa só metadata.

    classe (L1 v7): '1A'/'1B'/'1C' (mov) ou '1D' (documento orfao, sem ato
    processual). Pro 1D, o ramo de prompt e diferente (ver build no fim).
    """
    documentos_anexados = documentos_anexados or []
    has_docs = len(documentos_anexados) > 0

    # RAMO 1D — DOCUMENTO ÓRFÃO (doc sem ato processual vinculado). Schema de
    # saída continua MovFactSheetCard (decisão l1-schema-unico: tudo vira MOV_SCHEMA;
    # NÃO criar OrphanDocCard). natureza de_fluxo/acessorio entra como RACIOCÍNIO
    # (afeta data/tratamento), não como campo. resumo vai em resumo_ato.
    if classe == "1D":
        return _build_orfao_prompt(processo, mov, documentos_anexados)

    # FUNDACAO RESOLVIDA (L1 v7): em vez de polos crus, entrega o lado do Tomador
    # ja resolvido (ou instrucao de inferir grupo economico — caso Casas Bahia/
    # Via S.A) + a familia por materia. Ver fundacao.py + memory l1-invariante-fundacao.
    proc_block = (
        "=== CONTEXTO DA GARANTIA ===\n"
        + bloco_fundacao(processo)
        + familia_block(processo)
    )

    # CIRURGIAS do POC (l1_prompt_v2) — as melhorias COMPROVADAS sobre o v2.3 puro
    # (que reprovou; ver memory l1-teste-reprova). Injetadas no FIM de <regras_criticas>
    # (recência). Trabalhista só quando a matéria/classe indica (viés a injetar).
    _cirurgias = TRAVA_DECISAO + REGRA_TITULARIDADE
    if eh_trabalhista(processo):
        _cirurgias += MODULO_TRABALHISTA

    mov_meta_lines = [f"id: {mov.mov_id}"]
    if mov.data:
        mov_meta_lines.append(f"data: {mov.data}")
    if mov.tipo:
        mov_meta_lines.append(f"tipo_origem: {mov.tipo}")
    mov_meta = "\n  ".join(mov_meta_lines)

    texto = (mov.texto or "").strip()
    if len(texto) > 3000:
        texto = texto[:3000] + "..."

    # Conditional blocks — 4 secoes independentes, montadas conforme
    # disponibilidade dos inputs:
    # 1. DOCUMENTOS ANEXADOS: so quando has_docs=True
    # 2. RESUMO DO PROCESSO: so quando processo_resumo_ia presente
    # 3. MOV ANTERIOR: so quando mov_anterior_resumo presente (modo cadenciado)
    # 4. INSTRUCOES DE USO: condicional ao que foi montado acima
    if has_docs:
        docs_capped = documentos_anexados[:_DOC_LIST_CAP]
        docs_block = "\n\n".join(
            _summarize_doc(d, i, len(docs_capped)) for i, d in enumerate(docs_capped)
        )
        if len(documentos_anexados) > _DOC_LIST_CAP:
            docs_block += f"\n\n[+ {len(documentos_anexados) - _DOC_LIST_CAP} docs omitidos do prompt]"
        docs_section = f"""

=== DOCUMENTOS ANEXADOS A ESTA MOV ({len(documentos_anexados)} doc(s)) ===
{docs_block}
"""
    else:
        docs_section = ""

    processo_section = _processo_resumo_block(fallback_context)
    mov_anterior_section = _mov_anterior_block(fallback_context)

    # Instrucoes de uso variam por combinacao de inputs disponiveis.
    instrucoes_parts = []
    if has_docs:
        instrucoes_parts.append(
            "- O texto da publicacao no DJe pode ser GENERICO (ex: 'Anexo Juntado').\n"
            "- A informacao SUBSTANTIVA esta nos DOCUMENTOS ANEXADOS acima.\n"
            "- USE O CONTEUDO DOS DOCS pra preencher decisao, valores, peca_pivo, evento_garantia.\n"
            "- resumo_ato deve sintetizar O QUE ESTA NESTA MOV (incluindo os docs anexos),\n"
            "  NAO copiar o RESUMO DO PROCESSO ou MOV ANTERIOR.\n"
            "- Se ha SENTENCA ou ACORDAO entre os docs, preencha decisao.tem_decisao=true com\n"
            "  o sentido (favoravel/desfavoravel pro Tomador) extraido do dispositivo final."
        )
    else:
        instrucoes_parts.append(
            "- Sem doc anexo, voce SO TEM o snippet da publicacao + metadata desta mov.\n"
            "- NAO INVENTE conteudo. Se o snippet e generico (ex: 'Expedicao de outros\n"
            "  documentos', 'Juntada de peticao intercorrente'), classifique como\n"
            "  relevancia_merito='ruido' ou 'baixa' + tem_decisao=false + e_pivo=false.\n"
            "- confianca: 0.4-0.6 quando snippet generico, 0.6-0.8 quando snippet ja traz\n"
            "  teor (ex: 'Despacho: O juiz determinou X')."
        )
    if processo_section:
        instrucoes_parts.append(
            "- RESUMO DO PROCESSO e contexto de FUNDO (tese, partes, valor da causa).\n"
            "- NAO copie texto do RESUMO DO PROCESSO pro resumo_ato — esse campo descreve\n"
            "  SOMENTE o que aconteceu NESTA mov. Se a mov e ruido, o resumo_ato deve dizer\n"
            "  'Movimentacao sem teor substantivo', NAO repetir o resumo do processo."
        )
    if mov_anterior_section:
        instrucoes_parts.append(
            "- MOV ANTERIOR ajuda a resolver REFERENCIAS contextuais (pronomes 'o agravo',\n"
            "  'a decisao', 'a peticao') quando o texto desta mov alude a algo anterior.\n"
            "- NAO use a MOV ANTERIOR pra inferir conteudo desta mov. Conflito entre o teor\n"
            "  desta mov (snippet+docs) e a MOV ANTERIOR? Esta mov PREVALECE."
        )
    contexto_extra_section = (
        "\n\n=== INSTRUCOES PARA USO DO CONTEXTO ===\n" + "\n".join(instrucoes_parts)
        if instrucoes_parts else ""
    )

    return f"""Voce e analista juridico-securitario brasileiro especializado em SEGURO GARANTIA JUDICIAL.

Sua tarefa: extrair um FactSheet ESTRUTURADO de UMA movimentacao processual. Esse FactSheet sera agregado
pra calcular o risco de acionamento da apolice no merito.

<regras_criticas>

<regra_polos>
PRINCIPIO: o Tomador da apolice eh o cliente da seguradora — pode estar em
QUALQUER polo dependendo da classe processual. Identifique ONDE o Tomador esta
ANTES de mapear sentido.

PASSO 1 — Bucket pela classe:
- Execucao Fiscal, Cumprimento de Sentenca, Acao Monitoria contra o Tomador:
  polo_ativo = Fazenda/Credor; polo_passivo = TOMADOR (executado).
  Procedente da execucao = TOMADOR PERDEU. Improcedente = TOMADOR GANHOU.
- Embargos a Execucao Fiscal, Excecao de Pre-Executividade:
  polo_ativo = TOMADOR (embargante); polo_passivo = Fazenda (embargada).
  Procedente dos embargos = TOMADOR GANHOU. Improcedente = TOMADOR PERDEU.
- Acao Anulatoria de Debito Fiscal, Mandado de Seguranca, Acao Declaratoria,
  Repetitorio de Indebito, Acao Ordinaria Tributaria, Tutela Antecipada
  Antecedente, Tutela Cautelar Antecedente, Acao Cautelar:
  polo_ativo = TOMADOR (autor/impetrante/requerente); polo_passivo = Fazenda
  (re/coatora). Procedente da anulatoria/MS/tutela = TOMADOR GANHOU.
  Improcedente = TOMADOR PERDEU.
- Acao Civel Generica ("Procedimento Comum Civel"): identifique pelo objeto da
  acao + quem moveu. Nao assuma defaults.

PASSO 2 — Classe NAO listada acima:
NUNCA assuma "Execucao Fiscal default". Cruze polo_ativo/polo_passivo com nome
do Tomador na publicacao ou resumo do processo:
  - Tomador em polo_ativo => Tomador eh autor => procedente=favoravel
  - Tomador em polo_passivo => Tomador eh reu => procedente=desfavoravel

PASSO 3 — Se ambiguo: sentido=null + confianca<=0.5. NUNCA chute "Fazenda
autora default".

ATENCAO ao RESUMO DO PROCESSO (cascata IA): ele pode usar a preposicao "contra"
ambigua (ex: "Tutela Antecipada movida contra X" pode significar que X eh quem
propos a acao). NUNCA confie SO no resumo — sempre cruze com polo_ativo/
polo_passivo + nome do Tomador.
</regra_polos>

<regra_recursos>
PRINCIPIO: atos de RECURSO sao distintos de sentencas/acordaos de merito direto.
Pra recursos, sentido NAO depende de "procedente/improcedente" — depende de
QUEM eh o RECORRENTE + se o recurso foi PROVIDO ou NAO PROVIDO.

PASSO 1 — Identifique o RECORRENTE no texto:
- "Recurso da [PARTE]" / "Apelacao interposta por [PARTE]"
- "Recorrente: [PARTE]" / "(Juizo Recorrente)" / "Apelante: [PARTE]"
- "Embargos de declaracao opostos por [PARTE]"
- Quando nao explicito mas tem mov anterior com "Apelacao interposta pela Uniao
  Federal" e mov atual diz "Recurso conhecido e nao provido", recorrente = Uniao.

PASSO 2 — Mapeie PROVIDO/NAO PROVIDO -> sentido pro Tomador:
- PROVIDO (recurso aceito): "deu-se provimento", "recurso provido", "dou
  provimento", "acolho o recurso"
- NAO PROVIDO (recurso negado): "nao provido", "negado provimento", "nego
  provimento", "rejeitado o recurso", "improvido", "desprovido"

REGRA:
- Recorrente = TOMADOR (ou MESMO lado): provido=favoravel, nao provido=desfavoravel
- Recorrente = LADO OPOSTO (Fazenda, parte adversa): provido=desfavoravel,
  nao provido=FAVORAVEL (parte contraria perdeu, Tomador mantem vantagem)

EXEMPLO POSITIVO (MS GOL/Uniao, paradigma 2026-05-25):
  Mandado de Seguranca: GOL Linhas Aereas (polo_ativo, Tomador/impetrante)
  vs Uniao (polo_passivo, Fazenda/coatora).
  Mov: "Recurso da Uniao Federal foi conhecido e nao provido."
  -> Recorrente=Uniao=LADO OPOSTO -> Nao provido => Uniao PERDEU =>
     sentido=FAVORAVEL (NAO desfavoravel — erro classico do LLM).

EXEMPLO POSITIVO (EF, executado recorrente):
  Execucao Fiscal: Fazenda (polo_ativo, exequente) vs Tomador (polo_passivo,
  executado). Mov: "Recurso do executado provido."
  -> Recorrente=executado=Tomador -> Provido => sentido=FAVORAVEL.

CONTRAEXEMPLO: NUNCA assuma "Fazenda eh sempre quem recorre". Em MS/Anulatoria
geralmente quem recorre eh a Fazenda apos perder em 1g; em EF geralmente o
executado/Tomador recorre. Mas SEMPRE confirme no texto.

PASSO 3 — Se nao consegue identificar o recorrente: sentido=null + confianca<=0.5.

PASSO 4 — Natureza pra movs de recurso:
Use 'interlocutoria' SO se nao houve merito recursal (ex: nao conhecimento por
preliminar). Quando o recurso entra no merito (provido/nao provido), prefira
deixar natureza=null com sentido preenchido — L2 amarra via decisao_vigente.
</regra_recursos>

<regra_extincao_sem_merito>
DEFAULT (classes Tomador-REU como Execucao Fiscal): natureza='extinto_sem_merito'
=> sentido='neutro'. Extincao sem merito significa que juiz NAO julgou conteudo
da causa — ausencia de pressuposto, ilegitimidade, falta de interesse, transacao,
desistencia, perempcao, etc. NAO consolida divida nem julga risco. Mesmo se
processo for direcionado pra EF posterior, a EXTINCAO nao move risco — o que
move risco eh a EF subsequente. transito_certificado='true' aplica mas sentido
continua 'neutro' — extincao transitada NAO equivale improcedencia transitada.

EXCECAO (classes Tomador-AUTOR — Anulatoria, MS, Declaratoria, Repetitorio,
Tutela Cautelar/Antecipada Antecedente, Embargos a Execucao, Excecao Pre-
Executividade, Acao Rescisoria): natureza='extinto_sem_merito' => sentido=
'desfavoravel' (NAO neutro). Quando o Tomador propos a acao e ela foi extinta
SEM julgamento do conteudo (perda de objeto, carencia, abandono, ilegitimidade,
nao ajuizamento principal no prazo CPC 308 em cautelar antecedente), Tomador
PERDEU sem julgamento. A pretensao do Tomador (suspender exigibilidade, anular
debito, restituir indebito) NAO foi acolhida. A exigibilidade da Fazenda
CONTINUA. Equivale a derrota processual.

So eh 'neutro' em classe Tomador-autor quando extincao foi POR FAVOR ao Tomador
(homologacao de acordo, desistencia da Fazenda) — situacoes raras.

CASO PARADIGMA: Tutela Cautelar Antecedente proposta pelo Tomador pra suspender
exigibilidade tributaria, extinta por perda de objeto (Tomador nao ajuizou
principal no prazo CPC 308). Tomador PERDEU a cautelar — exigibilidade nao
foi suspensa. sentido='desfavoravel', natureza='extinto_sem_merito'.
</regra_extincao_sem_merito>
{_cirurgias}
</regras_criticas>

{proc_block}

=== MOVIMENTACAO ===
  {mov_meta}

  texto da publicacao (snippet):
  {texto}{docs_section}{processo_section}{mov_anterior_section}{contexto_extra_section}

=== INSTRUCOES POR CAMPO ===

1. resumo_ato (PT-BR ACENTUADO, TAMANHO PROPORCIONAL A RELEVANCIA): ato trivial = 1 frase;
   decisao/sentenca/evento de garantia = ate ~400 palavras se houver substancia. Teto e ESPACO,
   nao meta. O QUE aconteceu + DOC anexo se mencionado + PROXIMO PASSO se claro. NAO copie
   literalmente. Use tecnico-juridico direto.

2. {TAXONOMIA_TIPO_DOC}

   {RELEVANTE_GARANTIA}
   (NAO emita 'categoria' — ela e derivada por codigo a partir do tipo_doc.)

3. relevancia_merito: quanto este ato influencia a TESE/MERITO do processo principal:
   - alta: decisao de merito, sentenca, acordao, evento de garantia, intimacao de pagamento, transito
   - media: peticoes recursais, despachos saneadores, atos que viram o jogo procedural
   - baixa: despachos ordinatorios, publicacoes, atos de cartorio
   - ruido: cargas, baixas administrativas, intimacoes burocraticas sem conteudo

4. decisao: preencha SOMENTE quando ha DECISAO judicial nesta mov:
   - tem_decisao: true | false
   - sentido (DO PONTO DE VISTA DO TOMADOR = executado/embargante/impetrante):
     - favoravel: julga procedente embargos / improcedente execucao / concede liminar pro tomador
     - desfavoravel: rejeita defesa, mantem execucao, julga improcedente embargos
     - parcial: parte favoravel, parte nao
     - neutro: meramente processual sem ganhador claro (extincao SEM merito: neutro SE o Tomador
       e REU/executado; DESFAVORAVEL se o Tomador e AUTOR — ver <regra_extincao_sem_merito>)
   - instancia: 1g (juizo) | 2g (TJ/TRF) | stj | stf
   - natureza: procedente | improcedente | parcialmente_procedente | extinto_sem_merito |
     homologatoria | interlocutoria
   - transito_certificado: true SO se a mov CERTIFICA transito em julgado
   (Ver <regra_extincao_sem_merito> acima — regra dura por classe processual.)

   REGRA DURA — INEXIGIBILIDADE NAO eh EXTINCAO SEM MERITO:
   Quando uma sentenca em Embargos/Anulatoria/MS/Declaratoria ACOLHE A TESE
   do Tomador (inconstitucionalidade, nulidade da CDA, decadencia, prescricao
   da pretensao, etc) e declara "inexigibilidade do credito" / "inexigivel o
   tributo" / "nula a CDA": natureza='procedente' (NAO extinto_sem_merito).
   Foi julgamento DE MERITO acolhendo tese juridica — Tomador GANHOU no
   merito da causa. Sentido='favoravel'.

   Distincao chave: "extinguiu a execucao fiscal correlata" como CONSEQUENCIA
   da procedencia dos embargos NAO transforma a sentenca em extinto_sem_merito
   — o evento principal foi PROCEDENCIA dos embargos. A extincao da EF eh
   efeito reflexo. natureza='procedente'.

   extinto_sem_merito eh APENAS quando juiz NAO julgou conteudo (CPC 485):
   ilegitimidade, falta de pressuposto, carencia, perda de objeto, abandono,
   transacao homologatoria sem analise de tese.

5. evento_garantia:
   - tipo: apresentacao | aceitacao | recusa | levantamento | substituicao | reforco | nenhum
   - numero_apolice: numero da apolice no formato SUSEP (~24 digitos) se explicito; null se nao.
     NUNCA escreva a palavra 'string'.
   - motivo (SO quando tipo=recusa): "valor insuficiente", "seguradora nao admitida",
     "apolice vencida", etc. null caso contrario.

   (NAO emita 'status_garantia_pos_mov' nem 'tipo_garantia' nem 'cda' nem
    'processos_conexos_mencionados' — sao derivados, nao-usados ou desligados nesta versao.
    Foque nos campos abaixo.)

10. delta_risco: como esta mov muda o RISCO DE ACIONAMENTO da apolice vs estado anterior:
    - mudou: true | false
    - direcao: aumentou | diminuiu | inalterado
    - motivo: 1 frase PT-BR explicando POR QUE
    (Aumenta risco: sentenca desfavoravel sem suspensivo, transito, recusa de garantia, intimacao pagamento.
    Diminui risco: acordo, suspensao por RJ, decisao favoravel, transito favoravel.
    Inalterado: atos meramente procedimentais.)

11. valores (BRL, null se nao mencionado):
    - valor_causa, valor_debito_executado, valor_garantia

12. peca_pivo:
    - e_pivo: true se esta mov muda DECISIVAMENTE o estado do merito (sentenca, transito, acordo)
    - motivo: 1 frase explicando por que e (ou nao) pivo

13. data_real_ato (YYYY-MM-DD): se o texto menciona uma data ESPECIFICA do ato (sentenca em DD/MM/YYYY,
    acordo em DD/MM/YYYY) diferente da data de publicacao, registre aqui. null se igual a data.

14. confianca (0.0-1.0): confianca do LLM nesta classificacao. Use 0.9+ se ha doc anexo com decisao clara,
    0.7-0.8 se snippet detalhado sem doc, 0.5-0.7 se snippet generico com fallback context,
    < 0.5 se snippet ruidoso sem nada mais.

=== REGRAS DE OURO ===

A. NAO INVENTE. Se a mov+docs nao mencionam garantia/apolice, deixe evento_garantia.tipo='nenhum' e numero_apolice=null.
B. Sentido DO TOMADOR depende do polo (ver <regra_polos> no topo).
   - Em EF: Tomador=executado (polo passivo); improcedente da execucao = FAVORAVEL.
   - Em Embargos: Tomador=embargante (polo ativo); improcedente dos embargos = DESFAVORAVEL.
   - Em Anulatoria/MS: Tomador=autor (polo ativo); procedente da anulatoria = FAVORAVEL.
   Identifique o Tomador via polo_ativo/polo_passivo + classe ANTES de mapear sentido.
C. status_garantia_pos_mov deve refletir o ESTADO final: se a mov so APRESENTOU mas nao foi aceita,
   status='apresentado' (NAO 'aceito').
D. delta_risco.direcao=='aumentou' so quando ha sinal explicito desfavoravel. Apelacao com efeito
   suspensivo automatico (CPC art. 1.012) MANTEM inalterado mesmo apos sentenca de improcedencia.
E. Se a mov e ruido (carga, publicacao sem conteudo) E nao ha doc, use relevancia_merito='ruido' +
   delta_risco.mudou=false + e_pivo=false + confianca baixa. NAO sintetize dados falsos.
F. Se ha doc anexado, PRIORIZE o conteudo do doc sobre o snippet. O snippet pode ser
   apenas a notificacao da existencia do anexo.

<lembrete_final>
Antes de classificar decisao.sentido: cheque <regra_polos> no topo deste prompt.
Atos de recurso ("provido"/"nao provido"): cheque <regra_recursos> primeiro.
natureza='extinto_sem_merito': sentido='neutro' SE Tomador-REU; 'desfavoravel' SE Tomador-AUTOR (ver <regra_extincao_sem_merito>).
</lembrete_final>

Output: JSON estruturado conforme schema MovFactSheetCard (enforced via
response_schema do Gemini — nao precisa formato textual no prompt). Cada campo
tem descricao especifica no Pydantic. Echo de mov_id/data/tipo_origem deste input.
"""

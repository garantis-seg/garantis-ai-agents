"""Prompt pro mov_factsheet agent (engine v6_meritos camada 1).

REV2 2026-05-20 PM: doc-text first-class. Quando documentos_anexados nao
vazio, LLM le o texto do doc junto. Quando vazio, fallback formal com
processo summary + mov anterior.

REV3 2026-05-25 (piloto sequencial L1): fb_ctx pode ser passado SEMPRE
quando caller esta em modo cadenciado, mesmo com docs. Nesse caso o
prompt acrescenta bloco CONTEXTO ANTERIOR com instrucoes narrowadas
(uso so pra resolver pronouns/refs, docs prevalecem sobre contexto).
Memory: engine-v6-piloto-sequencial-l1-2026-05-25.
"""

from .schemas import DocAnexado, FallbackContext, MovInput, ProcessoContext


# Cap por doc anexado no prompt (Flash Lite 1M context aguenta, mas economiza)
_DOC_TEXT_CAP_CHARS = 8000
_DOC_LIST_CAP = 5  # max docs anexados por mov
_RESUMO_PROCESSO_CAP = 1000


def _summarize_doc(doc: DocAnexado, idx: int, total: int) -> str:
    """Bloco de 1 doc no prompt."""
    text = (doc.text_content or "").strip()
    truncated_note = ""
    if len(text) > _DOC_TEXT_CAP_CHARS:
        text = text[:_DOC_TEXT_CAP_CHARS]
        truncated_note = f"\n  [TRUNCADO a {_DOC_TEXT_CAP_CHARS} chars do original]"
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


def build_mov_factsheet_prompt(
    processo: ProcessoContext,
    mov: MovInput,
    documentos_anexados: list[DocAnexado] | None = None,
    fallback_context: FallbackContext | None = None,
) -> str:
    """Single-step prompt pra extrair 13 campos de UMA movimentacao.

    Quando documentos_anexados nao vazio: bloco DOCUMENTOS ANEXADOS no prompt,
    LLM le o doc text. Quando vazio: bloco FALLBACK CONTEXT com processo summary
    + mov anterior, LLM processa só metadata.
    """
    documentos_anexados = documentos_anexados or []
    has_docs = len(documentos_anexados) > 0

    proc_lines = [f"CNJ: {processo.cnj}"]
    if processo.classe:
        proc_lines.append(f"Classe: {processo.classe}")
    if processo.polo_ativo:
        proc_lines.append(f"Polo ativo: {processo.polo_ativo}")
    if processo.polo_passivo:
        proc_lines.append(f"Polo passivo: {processo.polo_passivo}")
    proc_block = "\n  ".join(proc_lines)

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

=== PROCESSO ===
  {proc_block}

=== MOVIMENTACAO ===
  {mov_meta}

  texto da publicacao (snippet):
  {texto}{docs_section}{processo_section}{mov_anterior_section}{contexto_extra_section}

=== REGRA DE LEITURA DE POLOS (CRITICA — leia antes de classificar sentido) ===

O Tomador da apolice eh o cliente da seguradora — pode estar em QUALQUER polo
dependendo da classe processual:

- Execucao Fiscal, Cumprimento de Sentenca, Acao Monitoria contra o Tomador:
  polo_ativo = Fazenda/Credor; polo_passivo = TOMADOR (executado).
  Procedente da execucao = TOMADOR PERDEU. Improcedente = TOMADOR GANHOU.

- Embargos a Execucao Fiscal, Excecao de Pre-Executividade:
  polo_ativo = TOMADOR (embargante); polo_passivo = Fazenda (embargada).
  Procedente dos embargos = TOMADOR GANHOU. Improcedente = TOMADOR PERDEU.

- Acao Anulatoria de Debito Fiscal, Mandado de Seguranca, Acao Declaratoria,
  Repetitorio de Indebito, Acao Ordinaria Tributaria, Tutela Antecipada
  Antecedente, Tutela Cautelar Antecedente, Acao Cautelar:
  polo_ativo = TOMADOR (autor/impetrante/requerente); polo_passivo =
  Fazenda (re/coatora).
  Procedente da anulatoria/MS/tutela = TOMADOR GANHOU. Improcedente = TOMADOR PERDEU.

- Acao Civel Generica ("Procedimento Comum Civel"): identifique pelo objeto da
  acao + quem moveu (autor pediu o que?). Nao assuma defaults.

REGRA DURA — CLASSE NAO LISTADA ACIMA:
Se a classe do processo NAO esta em nenhum dos buckets acima, NUNCA
assuma "Execucao Fiscal default". Em vez disso, cruze polo_ativo /
polo_passivo com o nome do Tomador na publicacao OU resumo do processo
pra identificar onde o Tomador esta:
  - Tomador em polo_ativo => Tomador eh autor => procedente=favoravel
  - Tomador em polo_passivo => Tomador eh reu => procedente=desfavoravel
Se ambiguo, sentido=null + confianca <=0.5.

ATENCAO ao RESUMO DO PROCESSO (cascata IA): ele pode usar a preposicao
"contra" ambigua (ex: "Tutela Antecipada movida contra X" pode significar
que X eh quem propos a acao). NUNCA confie SO no resumo — sempre cruze
com polo_ativo/polo_passivo + nome do Tomador.

REGRA DURA — 3 PASSOS pra preencher decisao.sentido:
1. Identifique o Tomador (cruze CNPJ/nome da publicacao com polo_ativo/polo_passivo).
2. Mapeie "procedente/improcedente" RELATIVO ao polo onde o Tomador esta.
   Em sentido juridico tradicional: procedente = autor venceu; improcedente = autor perdeu.
3. Se NAO conseguir identificar com confianca em qual polo o Tomador esta:
   sentido=null + confianca <=0.5. NUNCA chute "Fazenda autora" como default.

=== RECURSOS — REGRA CRITICA pra "Recurso X provido / nao provido" ===

ATOS DE RECURSO sao distintos de sentencas/acordaos de merito direto.
Pra recursos, sentido NAO depende de "procedente/improcedente" — depende
de QUEM eh o RECORRENTE + se o recurso foi PROVIDO ou NAO PROVIDO.

PASSO 1: identifique o RECORRENTE no texto.
Procure por:
- "Recurso da [PARTE]" / "Apelacao interposta por [PARTE]"
- "Recorrente: [PARTE]" / "(Juizo Recorrente)" / "Apelante: [PARTE]"
- "Embargos de declaracao opostos por [PARTE]"
- Quando nao explicito mas tem mov anterior com "Apelacao interposta
  pela Uniao Federal" e a mov atual diz "Recurso conhecido e nao provido",
  o recorrente eh a Uniao.

PASSO 2: mapeie PROVIDO/NAO PROVIDO -> sentido pro Tomador.

Termos equivalentes a PROVIDO (recurso aceito):
  "deu-se provimento", "recurso provido", "dou provimento", "acolho o recurso"

Termos equivalentes a NAO PROVIDO (recurso negado):
  "nao provido", "negado provimento", "nego provimento", "rejeitado o
  recurso", "improvido", "desprovido", "improvi o recurso"

REGRA:
  - Recorrente = TOMADOR (ou alguem do MESMO lado do Tomador):
    recurso PROVIDO -> sentido=favoravel
    recurso NAO PROVIDO -> sentido=desfavoravel

  - Recorrente = LADO OPOSTO ao Tomador (Fazenda, exequente contrario,
    parte adversa):
    recurso PROVIDO -> sentido=desfavoravel (a parte contraria ganhou)
    recurso NAO PROVIDO -> sentido=FAVORAVEL (a parte contraria perdeu,
                            o Tomador mantem a vantagem)

CASO PARADIGMA 1 (paradigma de bug 2026-05-25):
  Mandado de Seguranca: GOL Linhas Aereas (polo_ativo, Tomador/impetrante)
  vs Uniao Federal (polo_passivo, Fazenda/coatora).
  Mov: "Recurso da Uniao Federal foi conhecido e nao provido."
  Recorrente = Uniao = LADO OPOSTO ao Tomador GOL.
  Nao provido => Uniao PERDEU => GOL GANHOU.
  sentido=FAVORAVEL (NAO desfavoravel — erro classico do LLM).

CASO PARADIGMA 2:
  Execucao Fiscal: Fazenda (polo_ativo, exequente) vs Tomador (polo_passivo,
  executado). Mov: "Recurso do executado provido."
  Recorrente = executado = Tomador.
  Provido => Tomador GANHOU.
  sentido=FAVORAVEL.

PASSO 3: se NAO conseguir identificar o recorrente com confianca:
  sentido=null + confianca <=0.5. NUNCA assuma "Fazenda eh sempre quem
  recorre" — em MS / Anulatoria, geralmente quem recorre eh a Fazenda
  apos perder em 1g; em EF, geralmente o executado/Tomador recorre.

PASSO 4: natureza pra movs de recurso:
  Use 'interlocutoria' SO se nao houve merito recursal (ex: nao conhecimento
  por preliminar). Quando o recurso entra no merito (provido/nao provido),
  prefira deixar natureza=null com sentido preenchido — o L2 vai amarrar
  via decisao_vigente.

=== INSTRUCOES POR CAMPO ===

1. resumo_ato (~50 palavras PT-BR): O QUE aconteceu + DOC anexo se mencionado + PROXIMO PASSO se claro.
   NAO copie literalmente. Use tecnico-juridico direto.

2. categoria: classifique em UMA das opcoes (use 'outros' so se nada se encaixar):
   sentenca | acordao | decisao_merito | decisao_interlocutoria | despacho | peticao | publicacao
   intimacao | certidao | ato_ordinatorio | carga | baixa | conclusao | outros

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
     - neutro: meramente processual sem ganhador claro (extincao SEM merito SEMPRE neutro)
   - instancia: 1g (juizo) | 2g (TJ/TRF) | stj | stf
   - natureza: procedente | improcedente | parcialmente_procedente | extinto_sem_merito |
     homologatoria | interlocutoria
   - transito_certificado: true SO se a mov CERTIFICA transito em julgado

   REGRA DURA — EXTINCAO SEM MERITO:
   Quando natureza='extinto_sem_merito', sentido DEVE ser 'neutro', NUNCA
   'desfavoravel'. Extincao sem merito significa que o juiz NAO julgou o
   conteudo da causa — pode ser ausencia de pressuposto processual,
   ilegitimidade de parte, falta de interesse, transacao, desistencia,
   perempcao, etc. NAO consolida divida nem julga risco. Mesmo se o
   processo for direcionado pra Execucao Fiscal posterior, a EXTINCAO
   nao move risco — o que move risco e a Execucao Fiscal subsequente
   (que sera classificada quando suas movs aparecerem).
   transito_certificado='true' aplica a extincao mas sentido continua
   'neutro' — extincao transitada NAO equivale a improcedencia transitada.

5. evento_garantia:
   - tipo: apresentacao | aceitacao | recusa | levantamento | substituicao | reforço | nenhum
   - motivo (SO quando tipo=recusa): "valor insuficiente", "seguradora nao admitida",
     "apolice vencida", etc. null caso contrario.

6. status_garantia_pos_mov: estado da garantia DEPOIS desta mov:
   apresentado | aceito | recusado | levantado | substituido | nenhum
   (nenhum quando a mov nao trata da garantia)

7. tipo_garantia: quando mencionado:
   seguro_garantia | fianca_bancaria | carta_fianca | deposito_judicial | penhora |
   fiduciaria | outras | nenhum

8. cda:
   - numeros: lista de numeros literais de CDAs mencionados ([] se nenhum)
   - ente: estadual | municipal | federal_pgfn (null se nao identifica)
   - tributo: ICMS, ISS, IPVA, IRPJ, etc. (null se nao identifica)
   - valor_total: valor total em BRL quando explicito (null caso contrario)

9. apolice:
   - numero: numero literal mencionado (null se nao)
   - apresentada: true se a mov registra apresentacao (null se nao trata disso)
   - aceita: true se aceita pelo juizo, false se recusada, null se ambiguo/nao trata

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

13. proximos_passos: lista de acoes esperadas a partir deste ato.
    Ex: ["aguardar manifestacao da exequente", "preparar contrarrazoes", "agendar pericia"]

14. data_real_ato (YYYY-MM-DD): se o texto menciona uma data ESPECIFICA do ato (sentenca em DD/MM/YYYY,
    acordo em DD/MM/YYYY) diferente da data de publicacao, registre aqui. null se igual a data.

15. processos_conexos_mencionados: lista de CNJs (formato 7-2.4.1.2.4 ou 20 digitos) mencionados literalmente.

16. confianca (0.0-1.0): confianca do LLM nesta classificacao. Use 0.9+ se ha doc anexo com decisao clara,
    0.7-0.8 se snippet detalhado sem doc, 0.5-0.7 se snippet generico com fallback context,
    < 0.5 se snippet ruidoso sem nada mais.

=== REGRAS DE OURO ===

A. NAO INVENTE. Se a mov+docs nao mencionam apolice, deixe apolice.numero=null + apresentada=null + aceita=null.
B. Sentido DO TOMADOR depende do polo (ver REGRA DE LEITURA DE POLOS acima).
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

=== FORMATO DE SAIDA ===

Retorne APENAS JSON valido seguindo este shape exato:

{{
  "mov_id": "{mov.mov_id}",
  "data": {f'"{mov.data}"' if mov.data else "null"},
  "tipo_origem": {f'"{mov.tipo}"' if mov.tipo else "null"},
  "resumo_ato": "...",
  "categoria": "...",
  "relevancia_merito": "alta|media|baixa|ruido",
  "decisao": {{
    "tem_decisao": false,
    "sentido": null,
    "instancia": null,
    "natureza": null,
    "transito_certificado": false
  }},
  "evento_garantia": {{
    "tipo": "nenhum",
    "motivo": null
  }},
  "status_garantia_pos_mov": "nenhum",
  "tipo_garantia": "nenhum",
  "cda": {{
    "numeros": [],
    "ente": null,
    "tributo": null,
    "valor_total": null
  }},
  "apolice": {{
    "numero": null,
    "apresentada": null,
    "aceita": null
  }},
  "delta_risco": {{
    "mudou": false,
    "direcao": "inalterado",
    "motivo": null
  }},
  "valores": {{
    "valor_causa": null,
    "valor_debito_executado": null,
    "valor_garantia": null
  }},
  "peca_pivo": {{
    "e_pivo": false,
    "motivo": null
  }},
  "proximos_passos": [],
  "data_real_ato": null,
  "processos_conexos_mencionados": [],
  "confianca": 0.7
}}
"""

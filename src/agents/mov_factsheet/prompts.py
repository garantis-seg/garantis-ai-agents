"""Prompt pro mov_factsheet agent (engine v6_meritos camada 1).

REV2 2026-05-20 PM: doc-text first-class. Quando documentos_anexados nao
vazio, LLM le o texto do doc junto. Quando vazio, fallback formal com
processo summary + mov anterior.
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


def _fallback_block(ctx: FallbackContext | None) -> str:
    if not ctx:
        return "(sem fallback context)"
    lines = []
    if ctx.processo_resumo_ia:
        resumo = (ctx.processo_resumo_ia or "")[:_RESUMO_PROCESSO_CAP]
        lines.append(f"  RESUMO DO PROCESSO (cascata IA, cap {_RESUMO_PROCESSO_CAP} chars):")
        lines.append(f"    {resumo}")
    if ctx.mov_anterior_resumo:
        prev_cat = ctx.mov_anterior_categoria or "?"
        prev_dist = (
            f"ha {ctx.distance_dias_mov_anterior} dias atras"
            if ctx.distance_dias_mov_anterior is not None else "data anterior nao informada"
        )
        lines.append(f"  MOV ANTERIOR (categoria={prev_cat}, {prev_dist}):")
        lines.append(f"    {(ctx.mov_anterior_resumo or '')[:600]}")
    return "\n".join(lines) if lines else "(fallback context vazio)"


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

    # Conditional blocks
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

INSTRUCOES PARA DOCUMENTOS:
- O texto da publicacao no DJe pode ser GENERICO (ex: "Anexo Juntado").
- A informacao SUBSTANTIVA esta nos documento(s) acima.
- USE O CONTEUDO DOS DOCS pra preencher decisao, valores, peca_pivo, evento_garantia.
- texto_resumo deve sintetizar O QUE ESTA NOS DOCS (nao no snippet).
- Se ha SENTENCA ou ACORDAO entre os docs, preencha decisao.tem_decisao=true com
  o sentido (favoravel/desfavoravel pro Tomador) extraido do dispositivo final.
"""
        contexto_extra_section = ""
    else:
        docs_section = ""
        contexto_extra_section = f"""

=== FALLBACK CONTEXT (sem doc anexado disponivel) ===
{_fallback_block(fallback_context)}

INSTRUCOES PARA FALLBACK:
- Sem doc anexo, voce SO TEM o snippet da publicacao + metadata.
- Use o RESUMO DO PROCESSO pra entender contexto geral (tese, fase, partes).
- Use a MOV ANTERIOR pra inferir continuidade (ex: anterior="expedido mandado",
  esta="certifico cumprimento" => infira status).
- NAO INVENTE conteudo. Se o snippet e generico, classifique como
  relevancia_merito='ruido' OR 'baixa' + e_pivo=false + tem_decisao=false.
- confianca deve refletir limitacao: 0.4-0.6 quando snippet e generico,
  0.6-0.8 quando snippet ja traz teor (ex: "Despacho: O juiz determinou X").
"""

    return f"""Voce e analista juridico-securitario brasileiro especializado em SEGURO GARANTIA JUDICIAL.

Sua tarefa: extrair um FactSheet ESTRUTURADO de UMA movimentacao processual. Esse FactSheet sera agregado
pra calcular o risco de acionamento da apolice no merito.

=== PROCESSO ===
  {proc_block}

=== MOVIMENTACAO ===
  {mov_meta}

  texto da publicacao (snippet):
  {texto}{docs_section}{contexto_extra_section}

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
  Repetitorio de Indebito, Acao Ordinaria Tributaria:
  polo_ativo = TOMADOR (autor/impetrante); polo_passivo = Fazenda (re/coatora).
  Procedente da anulatoria/MS = TOMADOR GANHOU. Improcedente = TOMADOR PERDEU.

- Acao Civel Generica ("Procedimento Comum Civel"): identifique pelo objeto da
  acao + quem moveu (autor pediu o que?). Nao assuma defaults.

REGRA DURA — 3 PASSOS pra preencher decisao.sentido:
1. Identifique o Tomador (cruze CNPJ/nome da publicacao com polo_ativo/polo_passivo).
2. Mapeie "procedente/improcedente" RELATIVO ao polo onde o Tomador esta.
   Em sentido juridico tradicional: procedente = autor venceu; improcedente = autor perdeu.
3. Se NAO conseguir identificar com confianca em qual polo o Tomador esta:
   sentido=null + confianca <=0.5. NUNCA chute "Fazenda autora" como default.

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

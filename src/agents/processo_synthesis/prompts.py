"""Prompt pro processo_synthesis agent (engine v6_meritos camada 2).

REV2 2026-05-20 PM: aceita autos_raw_excerpt (primeiras 10 + ultimas 50 pgs do
autos.zip) pra 207/237 procs Monit com extraction_completed. DD6 do plano.
"""

import json
from typing import Any

from .schemas import ApoliceContextMin, DayFactSheetMin, MovFactSheetMin, ProcessoSynthesisRequest


_MAX_MOVS_INLINE = 50  # cap defensivo no input do prompt
_AUTOS_TEXT_CAP_CHARS = 60000  # DD6: cap absoluto 60k chars
_DOC_TEXT_CAP_CHARS = 6000     # DD4-alt: cap por doc dos autos
_MAX_DOCS_INLINE = 10           # DD4-alt: cap docs no prompt


# ── Matriz Daycoval (Probabilidade de Exito) ─────────────────────────────
# Criterios objetivos por tipo judicial. Removido criterio "Tese consolidada
# STJ/STF" da V1 (ambicioso demais, dependeria base externa). Pesos
# correspondem a score: provavel=1.0 | possivel=0.7 | poucas_chances=0.4 | remota=0.0001.

_DAYCOVAL_FISCAL = {
    "provavel": [
        "Materia com repercussao geral ou repetitivo definitivamente julgado favoravel ao contribuinte (Tomador)",
        "Materia exclusivamente de direito favoravel ao contribuinte (Tomador)",
        "Inexistencia de precedentes contrarios a materia discutida nos autos",
        "Parecer juridico ou Pericia tecnica conclusivo e favoravel ao contribuinte (Tomador)",
        "Mandado de Seguranca antecedente, favoravel ao contribuinte (Tomador) para o mesmo objeto",
        "Decisoes anteriores sob a mesma materia, favoraveis ao contribuinte (Tomador) que NAO dependam de analise dos fatos e producao de prova",
    ],
    "possivel": [
        "Jurisprudencia majoritariamente favoravel ao contribuinte (Tomador)",
        "Precedentes pontuais favoraveis a materia processual do contribuinte (Tomador)",
        "Tese favoravel ao contribuinte (Tomador) que dependa da producao de provas ou pericia tecnica",
        "Decisoes anteriores sob a mesma materia, favoraveis ao contribuinte (Tomador), porem, depende da analise dos fatos e producao de provas",
    ],
    "poucas_chances": [
        "Materia com jurisprudencia oscilante",
        "Tema/Materia nao possui tese de recurso repetitivo (IRDR)",
        "Decisoes desfavoraveis ao Tomador em Processo Administrativo que dependam da producao de provas no processo judicial",
    ],
    "remota": [
        "Jurisprudencia predominantemente desfavoravel ao contribuinte (Tomador)",
        "Decisoes precedentes contrarias a tese do contribuinte (Tomador)",
        "Tese defensiva residual ou protelatoria",
        "Processo em fase avancada com decisoes desfavoraveis ao contribuinte (Tomador)",
        "Materia predominantemente de direito desfavoravel ao contribuinte (Tomador)",
    ],
}

_DAYCOVAL_TRABALHISTA = {
    "provavel": [
        "Erro material ou aritmetico evidente nos calculos apresentados",
        "Extrapolacao/violacao da coisa julgada em fase de Execucao Trabalhista pelo Reclamante (Segurado)",
        "Materia exclusivamente de direito favoravel ao Reclamado (Tomador)",
        "Jurisprudencia pacificada favoravel ao Reclamado (Tomador)",
        "Prova documental incontestavel produzida pelo Reclamado (Tomador)",
        "Sumulas vinculantes/Orientacoes Jurisprudenciais favoraveis ao Reclamado (Tomador)",
    ],
    "possivel": [
        "Interpretacao do calculo favoravel ao Reclamado (Tomador)",
        "Jurisprudencia majoritariamente favoravel que dependa de producao de provas/pericia contabil",
        "Impugnacao/embargos bem fundamentados com tese favoravel ao Reclamado (Tomador)",
    ],
    "poucas_chances": [
        "Divergencia relevante sobre criterios de calculo ainda nao pacificado por Tribunais Superiores",
        "Jurisprudencia oscilante sobre o indice ou forma de calculo da condenacao",
    ],
    "remota": [
        "Titulo Executivo definitivo, cuja impugnacao tem vies meramente protelatorio",
        "Calculos da condenacao ja homologados na Execucao Definitiva sem materia para impugnacao",
        "Impugnacoes/decisoes anteriores desfavoraveis ao Reclamado (Tomador)",
        "Materia preclusa impugnada pelo Reclamado (Tomador)",
        "Penhora ou atos expropriatorios em curso na fase de Execucao Definitiva",
    ],
}

_DAYCOVAL_CIVEL = {
    "provavel": [
        "Materia com repercussao geral ou repetitivo definitivamente julgado favoravel ao garantido (Tomador)",
        "Materia exclusivamente de direito, sem necessidade de producao de provas pelo garantido (Tomador)",
        "Pedido juridicamente impossivel, prescrito ou decadente pela parte contraria",
        "Titulo Executivo com clausula contratual expressa, valida e usual, ja reconhecida como licita favoravel ao Tomador",
        "Inexistencia de precedentes contrarios a materia discutida nos autos",
        "Decisoes anteriores sob a mesma materia, favoraveis ao garantido (Tomador) que NAO dependam de analise dos fatos e producao de provas",
        "Provas produzidas favoraveis ao garantido (Tomador)",
        "Parecer juridico ou Pericia tecnica conclusivo e favoravel ao garantido (Tomador)",
    ],
    "possivel": [
        "Jurisprudencia majoritariamente favoravel ao garantido (Tomador)",
        "Precedentes pontuais favoraveis a materia processual do garantido (Tomador)",
        "Onus da prova nao cumprido pela parte contraria e favoraveis ao garantido (Tomador)",
        "Discussao de merito (decisoes) favoraveis ao Tomador em sede de recursos",
    ],
    "poucas_chances": [
        "Materia com jurisprudencia oscilante",
        "Tema/Materia nao possui tese de recurso repetitivo (IRDR)",
        "Discussao processual depende de producao de provas para conclusao da tese",
    ],
    "remota": [
        "Jurisprudencia predominantemente desfavoravel a tese do garantido (Tomador)",
        "Decisoes anteriores desfavoraveis ao garantido (Tomador)",
        "Provas produzidas desfavoraveis ao garantido (Tomador)",
        "Tese defensiva residual ou protelatoria",
        "Penhora ou atos expropriatorios em curso na fase de Execucao Definitiva/Cumprimento de Sentenca",
    ],
}

_DAYCOVAL_MATRIZES = {
    "fiscal": _DAYCOVAL_FISCAL,
    "trabalhista": _DAYCOVAL_TRABALHISTA,
    "civel": _DAYCOVAL_CIVEL,
}

_SCORE_BY_CLASS = {
    "provavel": 1.0,
    "possivel": 0.7,
    "poucas_chances": 0.4,
    "remota": 0.0001,
}


def _build_matriz_block(tipo_judicial: str) -> str:
    """Bloco com criterios objetivos da Matriz Daycoval per tipo."""
    matriz = _DAYCOVAL_MATRIZES.get(tipo_judicial, _DAYCOVAL_CIVEL)
    label_map = {"fiscal": "FISCAL", "trabalhista": "TRABALHISTA", "civel": "CIVEL"}
    label = label_map.get(tipo_judicial, "CIVEL")
    lines = [f"\n=== MATRIZ DAYCOVAL — PROBABILIDADE DE EXITO ({label}) ==="]
    lines.append(
        "Aplique os criterios abaixo (cite literalmente em criterios_aplicados[]).\n"
        "Score: provavel=1.0 | possivel=0.7 | poucas_chances=0.4 | remota=0.0001.\n"
    )
    for cls in ("provavel", "possivel", "poucas_chances", "remota"):
        score = _SCORE_BY_CLASS[cls]
        lines.append(f"\n[{cls.upper()}] (score={score}):")
        for bullet in matriz[cls]:
            lines.append(f"  - {bullet}")
    return "\n".join(lines)


def build_probabilidade_exito_prompt(req: ProcessoSynthesisRequest) -> str:
    """Prompt FOCADO so na Probabilidade de Exito Daycoval — call B do C2.

    Sem ruido das outras partes (estado_processual, decisao_vigente, etc.) —
    LLM concentra atencao na matriz e produz output mais consistente.
    Empirico v1: combinado com synthesis no mesmo prompt, gemini-2.5-flash
    omitia prob_exito em 100% das tentativas (smoke 1-merito 12151 + 50).
    """
    factsheets = req.mov_factsheets or []
    factsheets_sorted = sorted(factsheets, key=lambda f: (f.data or ""))
    if len(factsheets_sorted) > _MAX_MOVS_INLINE:
        factsheets_capped = factsheets_sorted[-_MAX_MOVS_INLINE:]
    else:
        factsheets_capped = factsheets_sorted

    timeline_block = "\n  ".join(_summarize_factsheet(f) for f in factsheets_capped) \
        or "(sem movimentacoes)"

    autos_block = _build_autos_block(req)
    docs_block = _build_documents_block(req)
    matriz_block = _build_matriz_block(req.tipo_judicial)

    header_parts = [f"CNJ: {req.processo_numero}"]
    if req.classe:
        header_parts.append(f"Classe: {req.classe}")
    header_parts.append(f"Tipo judicial: {req.tipo_judicial.upper()}")
    if req.polo_passivo:
        header_parts.append(f"Tomador (polo passivo): {req.polo_passivo}")
    header_block = "\n  ".join(header_parts)

    return f"""Voce e analista juridico brasileiro especializado em SEGURO GARANTIA JUDICIAL.

Sua UNICA tarefa: aplicar a Matriz Daycoval e classificar a PROBABILIDADE
DO TOMADOR TER EXITO neste processo. Sao 4 buckets — escolha 1.

=== PROCESSO ===
  {header_block}

=== TIMELINE DE FACTSHEETS (ordenados por data ASC) ===
  {timeline_block}
{autos_block}{docs_block}
{matriz_block}

=== INSTRUCOES ===

1. classificacao: escolha UM bucket da matriz acima
   (provavel | possivel | poucas_chances | remota).
   - "provavel" exige evidencia FORTE: decisao favoravel transitada,
     pericia/parecer favoravel no autos, jurisprudencia explicitamente firmada
     em sentido pro-tomador documentada.
   - "remota" exige evidencia FORTE em contrario: decisao desfavoravel
     transitada, penhora em curso, juris predominantemente contraria.
   - "possivel" e "poucas_chances" sao faixa cinza pra ambiguidade.
   - **Sem evidencia suficiente: prefira "poucas_chances"** (default conservador
     contra Baixo bias do v5), NAO "possivel" (vies otimista).

2. score: ESPELHE classificacao exato.
   provavel=1.0 | possivel=0.7 | poucas_chances=0.4 | remota=0.0001

3. criterios_aplicados: lista de strings com bullets LITERAIS copiados da
   matriz {req.tipo_judicial.upper()} acima. Minimo 1, max 4. NAO invente
   criterios.

4. justificativa: 1-3 frases PT-BR amarrando os criterios ao caso concreto
   (cite factsheet/autos quando relevante).

=== FORMATO DE SAIDA ===

Retorne APENAS JSON valido seguindo este shape:

{{
  "classificacao": "provavel|possivel|poucas_chances|remota",
  "score": 1.0,
  "criterios_aplicados": ["bullet literal copiado da matriz"],
  "justificativa": "1-3 frases amarrando criterios ao caso concreto"
}}
"""


def _summarize_factsheet(fs: MovFactSheetMin) -> str:
    """1 linha compacta por factsheet pro timeline do prompt."""
    parts = []
    if fs.data:
        parts.append(f"[{fs.data}]")
    parts.append(f"#{fs.mov_id}")
    if fs.categoria:
        parts.append(fs.categoria)
    if fs.relevancia_merito:
        parts.append(f"rel={fs.relevancia_merito}")
    if fs.resumo_ato:
        parts.append((fs.resumo_ato or "")[:200])

    decisao = fs.decisao or {}
    if decisao.get("tem_decisao"):
        d_parts = [f"DECISAO {decisao.get('natureza') or '?'}"]
        if decisao.get("instancia"):
            d_parts.append(decisao["instancia"])
        if decisao.get("sentido"):
            d_parts.append(decisao["sentido"])
        if decisao.get("transito_certificado"):
            d_parts.append("(TRANSITO)")
        parts.append(" ".join(d_parts))

    eg = fs.evento_garantia or {}
    if eg.get("tipo") and eg.get("tipo") != "nenhum":
        parts.append(f"GARANTIA:{eg['tipo']}" + (f" motivo={eg.get('motivo')}" if eg.get("motivo") else ""))

    if fs.status_garantia_pos_mov and fs.status_garantia_pos_mov != "nenhum":
        parts.append(f"status_garantia={fs.status_garantia_pos_mov}")

    dr = fs.delta_risco or {}
    if dr.get("mudou"):
        parts.append(f"DELTA_RISCO:{dr.get('direcao')} ({(dr.get('motivo') or '')[:80]})")

    pivo = fs.peca_pivo or {}
    if pivo.get("e_pivo"):
        parts.append(f"PIVO ({(pivo.get('motivo') or '')[:80]})")

    valores = fs.valores or {}
    val_parts = []
    if valores.get("valor_causa"):
        val_parts.append(f"causa=R$ {valores['valor_causa']:,.0f}".replace(",", "."))
    if valores.get("valor_debito_executado"):
        val_parts.append(f"debito=R$ {valores['valor_debito_executado']:,.0f}".replace(",", "."))
    if valores.get("valor_garantia"):
        val_parts.append(f"garantia=R$ {valores['valor_garantia']:,.0f}".replace(",", "."))
    if val_parts:
        parts.append("(" + ", ".join(val_parts) + ")")

    return " | ".join(parts)


def _summarize_apolice(ap: ApoliceContextMin) -> str:
    parts = []
    parts.append(f"Apolice {ap.numero_apolice or 'N/A'} ({ap.seguradora or 'sem seguradora'})")
    if ap.valor_is:
        parts.append(f"IS=R$ {ap.valor_is:,.0f}".replace(",", "."))
    if ap.apresentada is True:
        parts.append("apresentada")
    if ap.aceita is True:
        parts.append("ACEITA")
    elif ap.aceita is False:
        parts.append("RECUSADA")
    if ap.is_central_for_merito:
        parts.append("(central no merito)")
    return " | ".join(parts)


def _build_documents_block(req: ProcessoSynthesisRequest) -> str:
    """DD4-alt: bloco DOCUMENTOS DOS AUTOS quando documents_dos_autos nao vazio.

    Substitui o pivot mov-level (que dependia de hash matching nao recuperavel
    nos 39k links legacy). LLM da camada 2 cor-relaciona docs com factsheets.
    """
    docs = req.documents_dos_autos or []
    if not docs:
        return ""
    docs_capped = docs[:_MAX_DOCS_INLINE]
    lines = []
    for i, d in enumerate(docs_capped):
        text = (d.text_content or "").strip()
        truncated_note = ""
        if len(text) > _DOC_TEXT_CAP_CHARS:
            text = text[:_DOC_TEXT_CAP_CHARS]
            truncated_note = f"\n  [TRUNCADO a {_DOC_TEXT_CAP_CHARS} chars]"
        meta_parts = []
        if d.tipo:
            meta_parts.append(f"tipo: {d.tipo}")
        if d.titulo:
            meta_parts.append(f"titulo: {d.titulo}")
        if d.data_documento:
            meta_parts.append(f"data: {d.data_documento}")
        meta_parts.append(f"doc_key: {d.doc_key}")
        lines.append(f"--- DOC {i+1}/{len(docs_capped)} ---")
        lines.append("  " + " | ".join(meta_parts))
        lines.append("  texto:")
        lines.append("  " + text.replace("\n", "\n  "))
        if truncated_note:
            lines.append(truncated_note)
    omitted = len(docs) - len(docs_capped)
    omitted_note = f"\n[+ {omitted} docs omitidos do prompt]" if omitted > 0 else ""
    return (
        f"\n\n=== DOCUMENTOS DOS AUTOS ({len(docs)} disponivel{'is' if len(docs)!=1 else ''}, mostrando {len(docs_capped)}) ===\n"
        + "\n".join(lines)
        + omitted_note
        + "\n\nINSTRUCOES SOBRE DOCUMENTOS:\n"
        "- Os docs vem do autos do processo (provedor jusbrasil tipicamente)\n"
        "- Use o texto deles pra ENRIQUECER estado_processual, decisao_vigente,\n"
        "  peca_pivo_candidata e valores. NAO duplique - sintetize.\n"
        "- Quando doc aponta pra decisao/sentenca/acordao, cite doc_key em\n"
        "  evidence_artifacts com kind='cda'/'aiim'/'sentenca' (best fit).\n"
        "- Os factsheets (timeline) sao primarios pro estado processual;\n"
        "  docs complementam com texto literal das pecas."
    )


def _build_autos_block(req: ProcessoSynthesisRequest) -> str:
    """DD6 rev2: bloco AUTOS.ZIP TRECHO RAW quando autos_raw_excerpt presente.

    Retorna string vazia quando nao ha autos disponivel.
    """
    if not req.autos_raw_excerpt:
        return ""
    ax = req.autos_raw_excerpt
    text = (ax.text or "").strip()
    if not text:
        return ""
    if len(text) > _AUTOS_TEXT_CAP_CHARS:
        text = text[:_AUTOS_TEXT_CAP_CHARS] + "\n\n[TRUNCADO a 60k chars]"
    return (
        f"\n\n=== AUTOS.ZIP TRECHO RAW (peticao inicial + decisoes recentes, "
        f"{ax.pages_used} de {ax.total_pages} pgs) ===\n"
        f"{text}\n\n"
        "INSTRUCOES SOBRE AUTOS RAW:\n"
        "- Este e o TEXTO BRUTO do PDF do autos.zip merged (nao decomposto por mov).\n"
        "- Use como COMPLEMENTO aos factsheets (que sao a fonte primaria).\n"
        "- Quando ha conflito entre factsheet e autos: prefira a evidencia FACTUAL do autos\n"
        "  (texto literal) mas registre na justificativa.\n"
        "- Use o autos pra: confirmar peca-pivo, extrair valores numericos precisos,\n"
        "  identificar tese juridica da peticao inicial, ver dispositivos de sentencas/acordaos\n"
        "  literais."
    )


def _summarize_day_factsheet(d: DayFactSheetMin) -> str:
    """Bloco curto de 1 day_factsheet pro prompt."""
    parts = [f"[DIA {d.date or '?'}]"]
    if d.relevancia_para_merito:
        parts.append(f"relev={d.relevancia_para_merito}")
    if d.resumo_dia:
        parts.append(f"resumo: {d.resumo_dia[:200]}")
    eventos = d.eventos or []
    if eventos:
        eventos_str = "; ".join(
            f"{e.get('tipo', '?')}: {(e.get('descricao') or '')[:80]}"
            for e in eventos[:5]
        )
        parts.append(f"eventos: {eventos_str}")
    if d.decisao_do_dia and d.decisao_do_dia.get("tem_decisao"):
        sentido = d.decisao_do_dia.get("sentido", "?")
        natureza = d.decisao_do_dia.get("natureza", "?")
        parts.append(f"DECISAO: {sentido}/{natureza}")
    if d.evento_garantia_do_dia and d.evento_garantia_do_dia.get("tipo") not in (None, "nenhum"):
        parts.append(f"garantia: {d.evento_garantia_do_dia.get('tipo')}")
    return " | ".join(parts)


def build_processo_synthesis_prompt(req: ProcessoSynthesisRequest) -> str:
    """Build prompt que agrega mov_factsheets + day_factsheets + apolice context + autos_raw_excerpt."""
    factsheets = req.mov_factsheets or []
    factsheets_sorted = sorted(factsheets, key=lambda f: (f.data or ""))
    if len(factsheets_sorted) > _MAX_MOVS_INLINE:
        factsheets_capped = factsheets_sorted[-_MAX_MOVS_INLINE:]
        cap_note = f"\n  [{len(factsheets_sorted) - _MAX_MOVS_INLINE} movs anteriores omitidas para caber no prompt]\n"
    else:
        factsheets_capped = factsheets_sorted
        cap_note = ""

    timeline_block = cap_note + "\n  ".join(_summarize_factsheet(f) for f in factsheets_capped) \
        or "(sem movimentacoes mov-by-mov)"

    # Day_factsheets: tier Degradado-Dia. Coexiste com mov_factsheets quando
    # parte das movs tem FK e parte nao (intra-proc mixed).
    day_factsheets_sorted = sorted(req.day_factsheets or [], key=lambda d: (d.date or ""))
    days_block = "\n  ".join(_summarize_day_factsheet(d) for d in day_factsheets_sorted) \
        or "(sem day_factsheets — proc nao esta em tier Degradado-Dia OU nao ha docs sem FK)"

    apolice_block = "\n  ".join(_summarize_apolice(ap) for ap in (req.apolices or [])) \
        or "(sem apolice atrelada)"

    header_lines = [f"CNJ: {req.processo_numero}"]
    if req.classe:
        header_lines.append(f"Classe: {req.classe}")
    header_lines.append(f"Tipo judicial: {req.tipo_judicial}")
    if req.role_no_merito:
        header_lines.append(f"Papel no merito: {req.role_no_merito}")
    if req.polo_ativo:
        header_lines.append(f"Polo ativo (exequente): {req.polo_ativo}")
    if req.polo_passivo:
        header_lines.append(f"Polo passivo (tomador): {req.polo_passivo}")
    header_block = "\n  ".join(header_lines)

    autos_block = _build_autos_block(req)
    docs_block = _build_documents_block(req)

    classe_json = f'"{req.classe}"' if req.classe else "null"
    classe_code_json = req.classe_cnj_code if req.classe_cnj_code is not None else "null"
    role_json = f'"{req.role_no_merito}"' if req.role_no_merito else "null"

    return f"""Voce e analista juridico-securitario brasileiro especializado em SEGURO GARANTIA JUDICIAL.

Sua tarefa: sintetizar o estado atual do PROCESSO a partir dos FactSheets das movimentacoes
+ contexto da(s) apolice(s) + autos.zip (se disponivel). Output sera consumido pela
camada 3 (merito_synthesis) pra agregar risco do MERITO.

NOTA: `probabilidade_exito` (Matriz Daycoval) e calculada em CALL SEPARADA do C2;
NAO inclua esse campo neste output.

=== PROCESSO ===
  {header_block}

=== TIMELINE DE FACTSHEETS (mov_factsheets, ordenados por data ASC) ===
  {timeline_block}

=== DAY FACTSHEETS (tier Degradado-Dia, ordenados por data ASC) ===
  {days_block}

  INSTRUCOES PARA day_factsheets:
  - Existem quando ha docs nos autos com texto MAS sem vinculo nativo
    doc<->mov (caso tipico: Judit, Jusbrasil sem id de anexo). 1 card por dia
    agregando movs+docs do mesmo dia.
  - Coexistem com mov_factsheets no MESMO proc (intra-proc mixed tier).
    NAO sao duplicata: cobrem dias que mov_factsheet nao teve acesso a doc.
  - Use o RESUMO_DIA e EVENTOS pra extrair informacao FACTUAL (decisao,
    valores, peca-pivo) que mov_factsheet nao pegou.
  - Quando day_factsheet tem DECISAO mas mov_factsheet nao tem na mesma
    data: confie no day (que viu o doc) sobre mov (que viu so o snippet).
  - Confianca menor (~0.5-0.7) — correlacao multi-mov*multi-doc tem ruido.

=== APOLICE(S) ATRELADA(S) ===
  {apolice_block}{autos_block}{docs_block}

=== INSTRUCOES POR CAMPO ===

1. estado_processual: 1-2 frases PT-BR descrevendo o estado ATUAL do processo. Cite:
   - Em que instancia esta (1g/2g/etc) e fase (instrucao/sentenca/recurso/execucao/transito)
   - Se ha decisao vigente e qual o sentido
   - Se a garantia esta aceita ou nao

2. decisao_vigente: a decisao mais recente que governa o processo HOJE.
   - sentido: favoravel | desfavoravel | parcial | neutro (DO PONTO DE VISTA DO TOMADOR)
   - instancia: 1g | 2g | stj | stf
   - natureza: procedente | improcedente | parcialmente_procedente | extinto_sem_merito |
     homologatoria | interlocutoria
   - data: YYYY-MM-DD
   - transito_certificado: true SO se ha mov certificando transito
   - recorrida: true se houve recurso interposto contra esta decisao
   - Se NAO ha decisao de merito, deixe sentido/natureza=null. Use interlocutoria
     somente se ha decisao interlocutoria relevante (liminar, tutela, etc).

3. lifecycle_garantia: timeline ordenada por data dos eventos da garantia neste processo.
   Cada evento tem: data, mov_id, evento (apresentacao/aceitacao/recusa/levantamento/...),
   tipo_garantia (SG/fianca/deposito/...), status_pos (apresentado/aceito/recusado/...),
   motivo_recusa (so quando evento=recusa).
   Reconstrua a partir dos factsheets que tem evento_garantia.tipo != nenhum.

4. risco_processo_intermediario: classifique o risco deste PROCESSO (nao do merito) em:
   - Baixo: pendente sem decisao desfavoravel; embargos nao julgados; acordo vigente;
     trans favoravel; processo extinto sem merito; suspensao por causa externa (RJ)
   - Medio: improcedente em 1a inst COM apelacao pendente (efeito suspensivo presumido
     por CPC art. 1.012), EXCETO sinais explicitos de irregularidade (penhora online,
     intimacao para pagamento)
   - Alto: sentenca desfavoravel SEM recurso; mantido em 2a inst sem transito;
     intimacao para pagamento; jurisprudencia majoritaria pro-fazenda firmada
   - Altissimo: transito em julgado certificado desfavoravel; cumprimento de sentenca
     determinado contra o tomador

5. trajetoria_dentro_processo: olhando para a sequencia de delta_risco nos factsheets:
   - estavel: sem movs com delta_risco.mudou=true
   - deteriorando: maioria dos deltas tem direcao=aumentou
   - melhorando: maioria tem direcao=diminuiu
   - indefinida: misto/insuficiente

6. peca_pivo_candidata: a movimentacao mais decisiva pro estado atual. Use mov_id e data
   do factsheet com e_pivo=true mais recente. Se varios, escolha o mais "load-bearing"
   (sentenca > decisao interlocutoria > peticao). Motivo: 1 frase.

7. valor_em_disputa (BRL): melhor estimativa dos factsheets E autos raw. Use o mais
   recente/maior entre valor_causa e valor_debito_executado. null se nenhum disponivel.

8. valor_garantia (BRL): valor da apolice/garantia. Use prioritariamente o apolice card
   (apolices[].valor_is). Se nao, valores.valor_garantia dos factsheets ou autos raw.

9. confianca (0.0-1.0): quanto voce confia na sintese. Use 0.85+ quando ha decisao clara
   (factsheet com tem_decisao=true OU autos raw com dispositivo de sentenca/acordao),
   0.6-0.8 quando o estado e ambiguo, < 0.5 quando muitos factsheets vazios E sem autos.

10. evidence_artifacts: lista de {{mov_id, snippet, weight}} citando os 3-5 factsheets
    mais decisivos pra sua sintese. weight = high | medium | low.

11. tipo_judicial: ECHO do header (ja decidido upstream pelo classify_tipo_judicial).
    NAO recalcule, repita "{req.tipo_judicial}".

=== REGRAS DE OURO ===

A. NAO INVENTE. Se nenhum factsheet menciona apolice, deixe lifecycle_garantia=[].
B. O risco_processo_intermediario e do PROCESSO SO. NAO tente integrar conexos/merito aqui.
C. Se a apolice esta RECUSADA com motivo claro, isso NAO baixa o risco -- a fazenda
   pode buscar outra forma de garantia ou prosseguir pra penhora.
D. Apelacao tem efeito suspensivo automatico (CPC art. 1.012) -- improcedente em 1g
   + apelacao pendente = Medio, NAO Alto. Vire Alto somente com sinal explicito
   contrario (penhora deferida, intimacao para pagamento).
E. Suspensao e ambigua: explicite POR QUE no estado_processual (acordo/RJ/prejudicialidade/
   efeito suspensivo de recurso). Cada motivo move o risco diferente.
F. Quando ha autos raw disponivel, USE pra confirmar/refutar inferencias dos factsheets.
   Se o autos mostra dispositivo de sentenca mas nenhum factsheet capturou, registre na
   justificativa que o autos foi load-bearing.

=== FORMATO DE SAIDA ===

Retorne APENAS JSON valido seguindo este shape exato:

{{
  "processo_numero": "{req.processo_numero}",
  "classe": {classe_json},
  "classe_cnj_code": {classe_code_json},
  "role_no_merito": {role_json},
  "tipo_judicial": "{req.tipo_judicial}",
  "estado_processual": "1-2 frases descrevendo o estado atual (OBRIGATORIO, nao deixar vazio)",
  "decisao_vigente": {{
    "sentido": null,
    "instancia": null,
    "natureza": null,
    "data": null,
    "transito_certificado": false,
    "recorrida": false
  }},
  "risco_processo_intermediario": "Baixo|Medio|Alto|Altissimo",
  "lifecycle_garantia": [],
  "trajetoria_dentro_processo": "estavel|deteriorando|melhorando|indefinida",
  "peca_pivo_candidata": {{
    "mov_id": null,
    "data": null,
    "motivo": null
  }},
  "valor_em_disputa": null,
  "valor_garantia": null,
  "movs_processed": {len(factsheets_capped)},
  "confianca": 0.7,
  "evidence_artifacts": []
}}
"""

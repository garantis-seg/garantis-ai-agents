"""Prompt pro processo_synthesis agent (engine v6_meritos camada 2).

REV2 2026-05-20 PM: aceita autos_raw_excerpt (primeiras 10 + ultimas 50 pgs do
autos.zip) pra 207/237 procs Monit com extraction_completed. DD6 do plano.
"""

import json
from typing import Any

from .schemas import ApoliceContextMin, MovFactSheetMin, ProcessoSynthesisRequest


_MAX_MOVS_INLINE = 50  # cap defensivo no input do prompt
_AUTOS_TEXT_CAP_CHARS = 60000  # DD6: cap absoluto 60k chars
_DOC_TEXT_CAP_CHARS = 6000     # DD4-alt: cap por doc dos autos
_MAX_DOCS_INLINE = 10           # DD4-alt: cap docs no prompt


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


def build_processo_synthesis_prompt(req: ProcessoSynthesisRequest) -> str:
    """Build prompt que agrega mov_factsheets do processo + apolice context + autos_raw_excerpt."""
    factsheets = req.mov_factsheets or []
    factsheets_sorted = sorted(factsheets, key=lambda f: (f.data or ""))
    if len(factsheets_sorted) > _MAX_MOVS_INLINE:
        factsheets_capped = factsheets_sorted[-_MAX_MOVS_INLINE:]
        cap_note = f"\n  [{len(factsheets_sorted) - _MAX_MOVS_INLINE} movs anteriores omitidas para caber no prompt]\n"
    else:
        factsheets_capped = factsheets_sorted
        cap_note = ""

    timeline_block = cap_note + "\n  ".join(_summarize_factsheet(f) for f in factsheets_capped) \
        or "(sem movimentacoes)"

    apolice_block = "\n  ".join(_summarize_apolice(ap) for ap in (req.apolices or [])) \
        or "(sem apolice atrelada)"

    header_lines = [f"CNJ: {req.processo_numero}"]
    if req.classe:
        header_lines.append(f"Classe: {req.classe}")
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

Sua tarefa: sintetizar o estado atual de UM PROCESSO a partir dos FactSheets de suas movimentacoes
(mov_factsheets ja extraidos pela camada 1) + contexto da(s) apolice(s) atrelada(s)
+ trecho raw do autos.zip (quando disponivel, DD6).

Output e a camada 2 de 3 da engine v6. Output sera consumido pela camada 3 (merito_synthesis)
para agregar o risco do MERITO.

=== PROCESSO ===
  {header_block}

=== TIMELINE DE FACTSHEETS (mov_factsheets, ordenados por data ASC) ===
  {timeline_block}

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
  "estado_processual": "...",
  "decisao_vigente": {{
    "sentido": null,
    "instancia": null,
    "natureza": null,
    "data": null,
    "transito_certificado": false,
    "recorrida": false
  }},
  "lifecycle_garantia": [],
  "risco_processo_intermediario": "Baixo|Medio|Alto|Altissimo",
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

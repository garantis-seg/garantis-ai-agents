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
_MOV_ID_DISPLAY_CHARS = 8       # UUID prefix na exibicao (Bug 3 handoff)


def _short_mov_id(mov_id: str | None) -> str:
    """Trunca mov_id pra exibicao no prompt. UUID -> primeiros 8 chars.
    Numerico/outro formato -> retorna inteiro (compat legacy)."""
    if not mov_id:
        return "?"
    s = str(mov_id)
    # UUID detection: 36 chars com hifens em 8/13/18/23
    if (len(s) == 36 and s[8] == "-" and s[13] == "-"
            and s[18] == "-" and s[23] == "-"):
        return s[:_MOV_ID_DISPLAY_CHARS]
    return s


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

    monolith_block = _build_monolith_block(req)
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
{monolith_block}
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
    """1 linha compacta por factsheet pro timeline do prompt.

    mov_id renderizado como prefix de 8 chars (UUID estavel pos-Fase 2
    canonical layer — antes era canonical_event.id BIGINT volatil entre
    re-materializes, causava drift do prompt L2 entre cascades).
    """
    parts = []
    if fs.data:
        parts.append(f"[{fs.data}]")
    parts.append(f"#{_short_mov_id(fs.mov_id)}")
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


def _build_monolith_block(req: ProcessoSynthesisRequest) -> str:
    """Bloco MONOLITH FACTSHEET quando proc tier=monolitico (PDF blob sintetizado
    pela Camada 1 monolith_factsheet em 1 card estruturado).

    Full-RAG (memory engine-v6-pipeline-quality-tiers): SUBSTITUI os legacy
    _build_documents_block + _build_autos_block. L2 NAO recebe mais raw —
    monolith_factsheet (L1) ja fez essa sintese e expoe campos estruturados.

    Retorna string vazia quando proc nao esta em tier monolitico.
    """
    mf = req.monolith_factsheet
    if not mf:
        return ""

    lines = []
    if mf.resumo_executivo:
        lines.append(f"  resumo_executivo: {mf.resumo_executivo}")

    dv = mf.decisao_vigente or {}
    if dv.get("tem_decisao"):
        d_parts = [f"DECISAO_VIGENTE {dv.get('natureza') or '?'}"]
        if dv.get("instancia"):
            d_parts.append(dv["instancia"])
        if dv.get("sentido"):
            d_parts.append(dv["sentido"])
        if dv.get("data"):
            d_parts.append(f"({dv['data']})")
        if dv.get("transito_certificado"):
            d_parts.append("[TRANSITO CERTIFICADO]")
        lines.append("  " + " ".join(d_parts))

    eventos = mf.eventos_principais or []
    if eventos:
        ev_str = "; ".join(
            f"[{e.get('data','?')}] {e.get('tipo','?')}: {(e.get('descricao') or '')[:80]}"
            for e in eventos[:10]
        )
        lines.append(f"  eventos: {ev_str}")

    lc = mf.lifecycle_garantia or []
    if lc:
        lc_str = "; ".join(
            f"[{e.get('data','?')}] {e.get('evento','?')}/{e.get('tipo_garantia','?')}"
            for e in lc[:5]
        )
        lines.append(f"  lifecycle_garantia: {lc_str}")

    if mf.valor_em_disputa is not None:
        lines.append(f"  valor_em_disputa: R$ {mf.valor_em_disputa:,.2f}")
    if mf.valor_garantia is not None:
        lines.append(f"  valor_garantia: R$ {mf.valor_garantia:,.2f}")

    pivo = mf.peca_pivo or {}
    if pivo.get("descricao"):
        lines.append(f"  peca_pivo: [{pivo.get('data','?')}] {pivo['descricao']}")

    if mf.proximos_passos_provaveis:
        lines.append(f"  proximos_passos: {'; '.join(mf.proximos_passos_provaveis)}")

    if mf.confianca is not None:
        lines.append(f"  confianca: {mf.confianca}")

    pages_note = f" ({mf.pages_used} pgs lidas)" if mf.pages_used else ""
    body = "\n".join(lines) if lines else "  (monolith_factsheet vazio)"
    return (
        f"\n\n=== MONOLITH FACTSHEET (tier monolitico, PDF inteiro sintetizado{pages_note}) ===\n"
        f"{body}\n\n"
        "INSTRUCOES PARA monolith_factsheet:\n"
        "- Sintese ja-feita pela Camada 1 do PDF MONOLITICO inteiro (sem per-doc).\n"
        "- Confianca menor (~0.4-0.7) por construcao — leitura de PDF inteiro\n"
        "  sem mov-by-mov tem ruido. Mas eh sintese ESTRUTURADA, nao raw.\n"
        "- Use em complemento aos mov_factsheets + day_factsheets. Quando ambos\n"
        "  existem, factsheets per-mov/dia tem mais granularidade — prefira.\n"
        "- Quando monolith_factsheet eh a UNICA fonte (sem mov/day), use ele\n"
        "  como base, propagando a confianca menor pro card de saida."
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


_TIPO_RULES_FISCAL = """=== REGRAS TIPO-SPECIFIC (FISCAL) ===

Dinamica de execucao fiscal/contencioso tributario tem ritos proprios:

1. LEI 6.830/80: Execucao Fiscal exige garantia obrigatoria pra Embargos.
   Embargos NAO recebem efeito suspensivo automatico — depende do juiz
   (CPC 919, ja com Lei 6.830 art. 16 §1o). Embargos opostos SEM garantia
   sao indeferidos liminarmente.

2. CDA tem PRESUNCAO DE LIQUIDEZ E CERTEZA (Lei 6.830 art. 3o). Defesa do
   Tomador exige PROVA INEQUIVOCA de extincao/quitacao/nulidade. Despachos
   "rejeito a alegacao de [X]" tipicamente confirmam validade da CDA — sinal
   pro_fazenda.

3. ORDEM DE PREFERENCIA DA GARANTIA (Lei 6.830 art. 11): dinheiro > titulos
   da divida publica > pedras/metais > imoveis > moveis > direitos. Seguro
   garantia equiparado a dinheiro desde 2014 (art. 9o I-A). Recusa do seguro
   sem motivo proprio (so "prefiro penhora online") eh sinal NEGATIVO pra
   relacao Tomador-juizo, mas NAO move risco de merito sozinha.

4. PRESCRICAO: quinquenal (CTN art. 174) pra cobranca; intercorrente exige
   suspensao de 1 ano + 5 anos sem encontrar bens (Lei 6.830 art. 40 §4o,
   STJ Tema 566). Despachos arquivando provisoriamente sao GATILHO de
   prescricao — registre no estado_processual.

5. EXTINCAO POR PRESCRICAO INTERCORRENTE = pro_contribuinte (Fazenda perdeu
   sem julgamento de merito da CDA). NAO confundir com extincao por
   pagamento (que tambem favorece Tomador mas via quitacao, nao decadencia)."""

_TIPO_RULES_TRABALHISTA = """=== REGRAS TIPO-SPECIFIC (TRABALHISTA) ===

Reclamatoria trabalhista tem dinamica MUITO diferente do fiscal/civel:

1. POLO INVERTIDO PRO TOMADOR: Tomador eh sempre RECLAMADO (empregador),
   raramente reclamante. Improcedente = TOMADOR GANHOU. Procedente = TOMADOR
   PERDEU. Quase nunca aplicar regra "polo_ativo=Fazenda" — aqui eh
   trabalhista, autor eh empregado individual.

2. HIPOSSUFICIENCIA: juiz trabalhista tende a aceitar tese do reclamante
   em casos duvidosos (presuncao de veracidade pro empregado). Sentencas
   improcedentes sao mais "fortes" que procedentes (juiz teve que vencer
   a presuncao). Pesa pro_fazenda quando aparecem.

3. EXECUCAO TRABALHISTA: ja arranca da liquidacao + impulso oficio. Apolice
   geralmente entra na fase de EXECUCAO (apos sentenca/acordao com valor
   liquido). Pesquisar mov de "garantia do juizo" + "homologacao calculos".

4. ACORDO HOMOLOGADO: comum em trabalhista (CLT art. 855-B+, conciliacao
   pre-processual). Acordo eh categoria PROPRIA — NAO conta como
   procedente/improcedente. Risco apos acordo eh BAIXO se Tomador esta
   adimplente (parcelas em dia); ALTO se ha inadimplencia (mov de
   "intimacao pra pagamento de parcela acordada").

5. EXECUCAO PROVISORIA: trabalhista permite execucao provisoria (CLT art.
   899). Diferente do civel (que exige transito) e fiscal (que exige garantia
   da Lei 6.830). Risco preditivo sobe COM ACORDAO 2g mesmo SEM transito.

6. EXTINCAO POR ARQUIVAMENTO: ausencia de reclamante em audiencia (CLT 844)
   = extincao SEM merito = pro_fazenda/Tomador (Tomador ganhou de barato).
   Re-ajuizamento eh possivel — registre no trajetoria_motivo se houver
   processos relacionados ja conhecidos."""

_TIPO_RULES_CIVEL = """=== REGRAS TIPO-SPECIFIC (CIVEL) ===

Civel eh categoria heterogenea — varia muito por sub-dominio:

1. POLO AMBIGUO: Tomador pode ser AUTOR (Acao Anulatoria, MS, Declaratoria
   contra Fazenda) OU REU (Acao Civel Publica, indenizatoria por danos,
   cobranca contra Tomador). NAO assuma. Sempre cruzar polo com CNPJ/nome
   do Tomador via apolices/factsheets.

2. APELACAO COM EFEITO SUSPENSIVO AUTOMATICO (CPC art. 1.012): regra geral
   civel. Sentenca de improcedencia em 1g + apelacao pendente = Medio (NAO
   Alto). Vira Alto SO com sinal explicito contrario (cumprimento
   provisorio deferido, penhora online, intimacao pra pagamento).

3. CUMPRIMENTO DEFINITIVO vs PROVISORIO: definitivo (apos transito) = sinal
   ALTO pro Tomador devedor. Provisorio (durante recurso) = MEDIO se ha
   garantia, ALTO se nao.

4. SUSPENSAO POR ACORDO: comum em civel (transacao art. 840 CC). Sem
   inadimplencia = BAIXO; com inadimplencia = volta ao Alto/Medio
   dependendo do estagio.

5. ESPECIFICIDADES POR SUB-AREA:
   - Consumerista (CDC): inversao do onus probatorio (CDC 6 VIII) pesa
     pro_fazenda/Tomador-reu; juros e multas adicionais possiveis.
   - Empresarial: tende a tecnicidade alta (perdas raras pra Tomador
     incidentais; quando perdem, valores altos).
   - Familia/Sucessoes: improvavel ter apolice — fora do escopo normal."""


def _build_tipo_specific_block(tipo: str | None) -> str:
    """Dispatch de regras tipo-specific. Default civel se nao reconhecido."""
    if tipo == "fiscal":
        return _TIPO_RULES_FISCAL
    if tipo == "trabalhista":
        return _TIPO_RULES_TRABALHISTA
    return _TIPO_RULES_CIVEL


def build_processo_synthesis_prompt(req: ProcessoSynthesisRequest) -> str:
    """Build prompt que agrega mov_factsheets + day_factsheets + apolice context + autos_raw_excerpt.

    Sort do timeline e DETERMINISTICO: (data ASC, mov_id ASC). mov_id e
    cluster_id UUID estavel pos-Fase 2 (Bug 3 handoff). Mesmo input
    produz mesmo prompt entre cascades — drift L2 eliminado.
    """
    factsheets = req.mov_factsheets or []
    factsheets_sorted = sorted(
        factsheets,
        key=lambda f: (f.data or "", f.mov_id or ""),
    )
    if len(factsheets_sorted) > _MAX_MOVS_INLINE:
        factsheets_capped = factsheets_sorted[-_MAX_MOVS_INLINE:]
        cap_note = f"\n  [{len(factsheets_sorted) - _MAX_MOVS_INLINE} movs anteriores omitidas para caber no prompt]\n"
    else:
        factsheets_capped = factsheets_sorted
        cap_note = ""

    timeline_block = cap_note + "\n  ".join(_summarize_factsheet(f) for f in factsheets_capped) \
        or "(sem movimentacoes mov-by-mov)"

    # Day_factsheets: tier Degradado-Dia. Coexiste com mov_factsheets quando
    # parte das movs tem FK e parte nao (intra-proc mixed). Sort tie-break
    # por date string (sem mov_id em day).
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
        header_lines.append(f"Polo ativo: {req.polo_ativo}")
    if req.polo_passivo:
        header_lines.append(f"Polo passivo: {req.polo_passivo}")
    header_block = "\n  ".join(header_lines)

    monolith_block = _build_monolith_block(req)
    tipo_specific_block = _build_tipo_specific_block(req.tipo_judicial)

    classe_json = f'"{req.classe}"' if req.classe else "null"
    classe_code_json = req.classe_cnj_code if req.classe_cnj_code is not None else "null"
    role_json = f'"{req.role_no_merito}"' if req.role_no_merito else "null"

    return f"""Voce e analista juridico-securitario brasileiro especializado em SEGURO GARANTIA JUDICIAL.

Sua tarefa: sintetizar o estado atual do PROCESSO a partir dos FACTSHEETS da Camada 1
(mov_factsheet + day_factsheet + monolith_factsheet) + contexto da(s) apolice(s).
Output sera consumido pela camada 3 (merito_synthesis) pra agregar risco do MERITO.

ARQUITETURA FULL-RAG: voce SO recebe cards estruturados ja-sintetizados pela Camada 1
(nao recebe raw PDF nem docs cru). Confie nos cards — a Camada 1 fez o trabalho
de extracao FACTUAL com acesso ao texto. Sua tarefa eh AGREGAR + INTERPRETAR.

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
  {apolice_block}{monolith_block}

=== REGRA DE LEITURA DE POLOS (CRITICA — leia antes de classificar decisao_vigente.sentido) ===

O Tomador da apolice eh o cliente da seguradora — pode estar em QUALQUER polo
dependendo da classe processual. NAO assuma defaults.

- Execucao Fiscal, Cumprimento de Sentenca, Acao Monitoria contra o Tomador:
  polo_ativo = Fazenda/Credor; polo_passivo = TOMADOR (executado).
  Procedente da execucao = TOMADOR PERDEU. Improcedente = TOMADOR GANHOU.

- Embargos a Execucao, Excecao de Pre-Executividade:
  polo_ativo = TOMADOR (embargante); polo_passivo = Fazenda/credor.
  Procedente dos embargos = TOMADOR GANHOU. Improcedente = TOMADOR PERDEU.

- Acao Anulatoria de Debito Fiscal, Mandado de Seguranca, Acao Declaratoria,
  Repetitorio de Indebito, Acao Ordinaria Tributaria:
  polo_ativo = TOMADOR (autor/impetrante); polo_passivo = Fazenda (re/coatora).
  Procedente da anulatoria/MS = TOMADOR GANHOU. Improcedente = TOMADOR PERDEU.

- Procedimento Comum Civel generico: identifique pelo objeto + quem moveu.

REGRA DURA — 3 PASSOS pra decisao_vigente.sentido (e p/ ler factsheets que
trazem decisao.sentido invertido por erro de leitura da Camada 1):
1. Identifique o Tomador (cruze CNPJ/nome em uma apolice/factsheet com
   polo_ativo e polo_passivo do header).
2. Mapeie "procedente/improcedente" RELATIVO ao polo onde o Tomador esta:
   procedente = autor venceu; improcedente = autor perdeu.
3. Se nao identificar Tomador com confianca: sentido=null + confianca <=0.5.
   NUNCA chute "polo_ativo=Fazenda" como default.

CAVEAT — Camada 1 pode ter classificado decisao.sentido errado neste mesmo
processo (mesmo bug). Releia os factsheets com lente de polo: se um factsheet
trouxer sentido='desfavoravel' em um caso de Anulatoria onde Tomador eh autor
e a natureza eh 'procedente', a Camada 1 errou — corrija no estado_processual
+ decisao_vigente.sentido.

{tipo_specific_block}

=== INSTRUCOES POR CAMPO ===

1. estado_processual: 1-2 frases PT-BR descrevendo o estado ATUAL do processo. Cite:
   - Em que instancia esta (1g/2g/etc) e fase (instrucao/sentenca/recurso/execucao/transito)
   - Se ha decisao vigente e qual o sentido
   - Se a garantia esta aceita ou nao

2. decisao_vigente: a decisao MAIS LOAD-BEARING que governa o processo HOJE.
   "Mais recente" NAO eh sinonimo de "mais load-bearing" — use a hierarquia:

   HIERARQUIA DE LOAD-BEARING (forte → fraca):
     transito_em_julgado >> acordao (2g+) >> sentenca (1g) >>
     decisao homologatoria >> decisao interlocutoria

   REGRA DE PERMANENCIA: uma sentenca/acordao passada CONTINUA sendo
   decisao_vigente ate que ela seja:
     (a) reformada por instancia superior (nova sentenca/acordao substituindo), OU
     (b) transitada em julgado (vira o estado final), OU
     (c) substituida por outra decisao de mesmo OU maior nivel hierarquico.
   Interlocutorias RECENTES (suspensao, conclusao, despacho, penhora online,
   bloqueio, novo prazo) NAO substituem decisao de merito anterior — elas
   apenas MODULAM o estado_processual. Reflete-as em estado_processual com
   contexto, mas mantenha decisao_vigente ancorada na ultima decisao de merito.

   EXEMPLO CONCRETO: processo tem sentenca de improcedencia de Embargos em 2022
   + apelacao pendente + decisao interlocutoria de bloqueio online em 2024.
   decisao_vigente = a SENTENCA DE 2022 (sentido desfavoravel ao Tomador
   embargante), NAO a interlocutoria de 2024. O bloqueio entra no
   estado_processual ("execucao em curso com bloqueio determinado").

   - sentido: favoravel | desfavoravel | parcial | neutro (DO PONTO DE VISTA DO TOMADOR;
     aplique a REGRA DE LEITURA DE POLOS acima — NAO assuma Fazenda=autor por default)
   - instancia: 1g | 2g | stj | stf
   - natureza: procedente | improcedente | parcialmente_procedente | extinto_sem_merito |
     homologatoria | interlocutoria
   - data: YYYY-MM-DD
   - transito_certificado: true SO se ha mov certificando transito
   - recorrida: true se houve recurso interposto contra esta decisao
   - Se NAO ha decisao de merito (sentenca/acordao/homologatoria), deixe
     sentido/natureza=null. Use interlocutoria SOMENTE se TOTAL ausencia de
     decisao de merito E a interlocutoria for relevante (liminar concedida,
     tutela antecipada, etc — algo com substancia decisoria, NAO procedural).

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

G. ESTABILIDADE TEMPORAL — decisao_vigente NAO deve oscilar entre cuts/snapshots
   sucessivos do MESMO processo so porque chegaram movs procedurais novos.
   Backtest 2026-05-24 detectou padrao de instabilidade: cuts antigos
   classificaram corretamente (ancorados em sentenca/acordao), cut recente
   trocou pra interlocutoria nova (despacho/conclusao/bloqueio) e mudou
   sentido — gerando "miss" mesmo sem nada de merito ter mudado.
   Pergunta de auto-check antes de emitir decisao_vigente:
     "Esta decisao_vigente que estou propondo eh a mesma que eu proporia
      se nao tivesse os ultimos 6 meses de movs procedurais? Se NAO,
      e a decisao de merito anterior continua valida (nao reformada/
      transitada), MANTENHA a anterior."

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

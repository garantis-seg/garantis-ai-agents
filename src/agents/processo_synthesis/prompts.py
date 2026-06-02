"""Prompt pro processo_synthesis agent (engine v6_meritos camada 2).

REV2 2026-05-20 PM: aceita autos_raw_excerpt (primeiras 10 + ultimas 50 pgs do
autos.zip) pra 207/237 procs Monit com extraction_completed. DD6 do plano.

REV3 2026-05-25 (P1+P2 do prompt-engineering FINDINGS — v2.1):
- Removido bloco "=== FORMATO DE SAIDA ===" dos 2 prompts (~80 linhas
  duplicando shape JSON). Output enforced via response_schema=
  ProcessoSynthesisCard / ProbabilidadeExito em agent.py.
- REGRA DE LEITURA DE POLOS movida do meio (era linha 618-651) pro TOPO
  em bloco <regras_criticas> XML. Combate Lost-in-the-Middle.
- <lembrete_final> no fim como recency anchor.
- Tipo-specific blocks (FISCAL/TRABALHISTA/CIVEL) mantidos no meio — sao
  contextuais por bucket, nao competem com regras universais.
"""

import json
import os
from typing import Any

from .schemas import ApoliceContextMin, DayFactSheetMin, MovFactSheetMin, ProcessoSynthesisRequest


# PR7.3 (2026-05-31): _flag_enabled wrapper removido — unico caller era
# JURISPRUDENCIA_BLOCK_ENABLED do bloco interno (dropado em PR7.2).
# Provider externo jurisprudencias.ai eh single source jurisprudencial agora.

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
# Extraida em 2026-05-31 (PR2 Architecture D) pra
# garantis_shared.engine_v6.matrices.daycoval. Mantemos aliases legacy
# (_DAYCOVAL_*, _SCORE_BY_CLASS, _build_matriz_block) pra calls existentes
# nesse modulo continuarem funcionando byte-identical. PR3+ remove
# dependencia se necessario.
from garantis_shared.engine_v6.matrices import (
    DAYCOVAL_CIVEL as _DAYCOVAL_CIVEL,
    DAYCOVAL_FISCAL as _DAYCOVAL_FISCAL,
    DAYCOVAL_MATRIZES as _DAYCOVAL_MATRIZES,
    DAYCOVAL_SCORE_BY_CLASS as _SCORE_BY_CLASS,
    DAYCOVAL_TRABALHISTA as _DAYCOVAL_TRABALHISTA,
)
from garantis_shared.engine_v6.matrices.daycoval import (
    build_matriz_block_compat as _build_matriz_block,
)


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

Output: JSON estruturado conforme schema ProbabilidadeExito (enforced via
response_schema do Gemini — nao precisa formato textual no prompt).
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
   - Familia/Sucessoes: improvavel ter apolice — fora do escopo normal.

6. EXTINCAO SEM MERITO EM ACAO TOMADOR-AUTOR:
   Ver <regra_extincao_tomador_autor> no topo. Caso paradigma: Tutela Cautelar
   Antecedente proposta pelo Tomador, extinta por perda de objeto (Tomador
   nao ajuizou principal no prazo CPC 308). Tomador PERDEU sem julgamento —
   a exigibilidade nao foi suspensa. Sentido='desfavoravel', natureza=
   'extinto_sem_merito'."""


def _build_tipo_specific_block(tipo: str | None) -> str:
    """Dispatch de regras tipo-specific. Default civel se nao reconhecido."""
    if tipo == "fiscal":
        return _TIPO_RULES_FISCAL
    if tipo == "trabalhista":
        return _TIPO_RULES_TRABALHISTA
    return _TIPO_RULES_CIVEL


# PR7.2 (2026-05-31): _build_tese_juris_block REMOVIDO. Bloco juris interno
# (curadoria ref.tese_jurisprudencia) dropado em favor do provider externo
# jurisprudencias.ai. Substituido por _build_juris_externa_block (abaixo).


def _build_juris_externa_block(je) -> str:
    """Renderiza jurisprudencia externa (provider jurisprudencias.ai) (PR3).

    Architecture D — bloco PARALELO ao tese_jurisprudencia interno. Quando
    JURISPRUDENCE_PATH_ENABLED=off, este field eh None upstream e este
    helper nao eh chamado (caller short-circuita). Quando present:
    header + tally + top 3 ementas (process_number + publication_date +
    excerpt curto + url). LLM deve emit risco_jurisprudencial baseado nele.
    """
    if je is None:
        # Should not be reached — caller checks before invocation. Guard so
        # mudancas upstream no schema nao quebrarem byte-identical em off.
        return "(sem jurisprudencia externa — flag off ou tribunal sem mapping)"
    lines = []
    parts = []
    if je.tribunal:
        parts.append(f"tribunal={je.tribunal}")
    if je.resultado_majoritario:
        parts.append(f"resultado={je.resultado_majoritario}")
    if je.n_hits is not None:
        parts.append(f"n_hits={je.n_hits}")
    if je.cached is not None:
        parts.append(f"cached={je.cached}")
    lines.append("  " + " | ".join(parts) if parts else "  (sem metadata)")
    top = je.top_decisions or []
    if top:
        lines.append("  Top 3 ementas (provider):")
        for i, d in enumerate(top[:3], start=1):
            pn = d.get("process_number") or "?"
            pub = d.get("publication_date") or "?"
            excerpt = (d.get("excerpt") or "").strip().replace("\n", " ")
            if len(excerpt) > 300:
                excerpt = excerpt[:300] + "…"
            lines.append(f"    [{i}] {pn} ({pub}): {excerpt}")
    else:
        lines.append("  (sem ementas retornadas pelo provider)")
    return "\n".join(lines)


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

    tipo_specific_block = _build_tipo_specific_block(req.tipo_judicial)
    # PR7.2 (2026-05-31): tese_juris_section (bloco JURISPRUDENCIA DA TESE
    # interno) REMOVIDO. Provider externo jurisprudencias.ai (jurisprudencia_externa)
    # eh unica fonte. Curadoria interna ref.tese_jurisprudencia DROPPED.
    tese_juris_section = ""

    # PR6 Architecture D: bloco "Decomposicao Orthogonal" SEMPRE renderizado
    # (independente da flag JURISPRUDENCE_PATH_ENABLED). Forca o LLM a emit
    # risco_factual + risco_jurisprudencial separados em TODOS cascades.
    # PR7.2 (2026-05-31): em flag=off, juris vem APENAS de jurisprudencia_externa
    # (provider). Quando provider unavailable, LLM emit Indeterminado.
    juris_externa_header = ""
    if req.jurisprudencia_externa is not None:
        juris_externa_header = (
            "\n=== JURISPRUDENCIA EXTERNA (provider jurisprudencias.ai) ===\n"
            + _build_juris_externa_block(req.jurisprudencia_externa)
        )

    juris_sources_clause = (
        "jurisprudencia_externa PROVIDER (acima)"
        if req.jurisprudencia_externa is not None
        else "(NENHUMA fonte juris disponivel — emit risco_jurisprudencial=Indeterminado)"
    )

    risk_decomposition_section = (
        juris_externa_header
        + "\n\nINSTRUCAO — DECOMPOSICAO ORTHOGONAL (Architecture D, sempre emit):\n"
        "  - risco_factual:        derive APENAS do estado processual + tier +\n"
        "                          decisao_vigente + lifecycle (Matriz Daycoval pura).\n"
        "                          IGNORE jurisprudencia. Mesma logica que voce usaria\n"
        "                          em risco_processo_intermediario, mas SEM peso de tese.\n"
        f"  - risco_jurisprudencial: derive APENAS de {juris_sources_clause}.\n"
        "                          IGNORE estado processual. Quando NAO ha sinal forte\n"
        "                          (resultado oscilante/indeterminado, sem mapeamento de\n"
        "                          tese, n_hits<3 no provider), emit 'Indeterminado' —\n"
        "                          NUNCA chute Baixo por default.\n"
        "                          Mapeamento sugerido (provider externo):\n"
        "                            resultado='pro_contribuinte' -> Baixo\n"
        "                            resultado='pro_fazenda'      -> Alto\n"
        "                            resultado='dividida'         -> Medio\n"
        "                            resultado='indeterminado'    -> Indeterminado\n"
        "  AMBOS sao orthogonal — NAO combine sinais cruzados. Camada 3 agrega via\n"
        "  matriz determ + A/B test entre prompts (PR6).\n"
        "  risco_processo_intermediario LEGACY tambem eh emitido (compat backward).\n"
    )

    return f"""Voce e analista juridico-securitario brasileiro especializado em SEGURO GARANTIA JUDICIAL.

Sua tarefa: sintetizar o estado atual do PROCESSO a partir dos FACTSHEETS da Camada 1
(mov_factsheet + day_factsheet) + contexto da(s) apolice(s).
Output sera consumido pela camada 3 (merito_synthesis) pra agregar risco do MERITO.

ARQUITETURA FULL-RAG: voce SO recebe cards estruturados ja-sintetizados pela Camada 1
(nao recebe raw PDF nem docs cru). Confie nos cards — a Camada 1 fez o trabalho
de extracao FACTUAL com acesso ao texto. Sua tarefa eh AGREGAR + INTERPRETAR.

NOTA: `probabilidade_exito` (Matriz Daycoval) e calculada em CALL SEPARADA do C2;
NAO inclua esse campo neste output.

<regras_criticas>

<regra_polos>
PRINCIPIO: o Tomador da apolice pode estar em QUALQUER polo dependendo da classe
processual. Identifique ONDE o Tomador esta ANTES de mapear decisao_vigente.sentido.

PASSO 1 — Bucket pela classe:
- Execucao Fiscal, Cumprimento de Sentenca, Acao Monitoria contra o Tomador:
  polo_ativo = Fazenda/Credor; polo_passivo = TOMADOR (executado).
  Procedente da execucao = TOMADOR PERDEU. Improcedente = TOMADOR GANHOU.
- Embargos a Execucao, Excecao de Pre-Executividade:
  polo_ativo = TOMADOR (embargante); polo_passivo = Fazenda/credor.
  Procedente dos embargos = TOMADOR GANHOU. Improcedente = TOMADOR PERDEU.
- Acao Anulatoria, Mandado de Seguranca, Acao Declaratoria, Repetitorio
  de Indebito, Acao Ordinaria Tributaria, Tutela Antecipada/Cautelar Antecedente:
  polo_ativo = TOMADOR (autor/impetrante); polo_passivo = Fazenda (re/coatora).
  Procedente = TOMADOR GANHOU. Improcedente = TOMADOR PERDEU.
- Procedimento Comum Civel generico: identifique pelo objeto + quem moveu.

PASSO 2 — Identifique o Tomador (cruze CNPJ/nome em apolice/factsheet com
polo_ativo e polo_passivo do header).

PASSO 3 — Mapeie "procedente/improcedente" RELATIVO ao polo do Tomador:
procedente = autor venceu; improcedente = autor perdeu. Se nao identificar
com confianca: sentido=null + confianca<=0.5. NUNCA chute "polo_ativo=Fazenda
default".

CAVEAT — Camada 1 pode ter classificado decisao.sentido errado. Releia os
factsheets com lente de polo: se um factsheet trouxer sentido='desfavoravel'
em Anulatoria onde Tomador eh autor e natureza='procedente', Camada 1 errou —
corrija no estado_processual + decisao_vigente.sentido.
</regra_polos>

<regra_extincao_tomador_autor>
Em classes onde Tomador eh AUTOR (Anulatoria, MS, Declaratoria, Repetitorio,
Tutela Antecedente, Embargos a Execucao, Excecao Pre-Executividade) e a
acao foi extinta SEM RESOLUCAO DE MERITO (CPC 485 — perda de objeto, carencia
de acao, abandono, ilegitimidade, etc): Tomador PERDEU sem julgamento.
A pretensao do Tomador NAO foi acolhida. A exigibilidade da Fazenda CONTINUA.
decisao_vigente.sentido = 'desfavoravel' (NAO neutro, NAO favoravel).
natureza = 'extinto_sem_merito'.

So eh 'neutro' quando a extincao foi POR FAVOR ao Tomador (homologacao de
acordo, desistencia da Fazenda) — raras em Tomador-autor.
</regra_extincao_tomador_autor>

<regra_jurisprudencia>
A jurisprudencia da tese canonica (campo tese_jurisprudencia abaixo, quando
presente) eh INPUT DIRETO no risco_processo_intermediario. Substituiu o
double-counting antigo (Matriz Daycoval implicito + regras G/G.1/G.2 em L3).

GLOSSARIO `resultado_majoritario` (6 valores):
- pro_contribuinte_firmado: tese STF/STJ vinculante FAVORAVEL ao Tomador
  (vento de cauda forte — empurra Baixo)
- pro_fazenda_firmado: tese STF/STJ vinculante DESFAVORAVEL ao Tomador
  (vento contra forte — empurra Alto)
- oscilante: decisoes divididas entre turmas/instancias — sem majoritario
  claro (NAO move risco; governado pelo estado da causa)
- pendente_julgamento_superior: tema afetado, aguarda STF/STJ (estado atual
  domina, MAS cite julgamento pendente como risco prospectivo)
- tese_nova: sem historico significativo (governado pelo estado, baixa confianca)
- nao_classificada: catch-all generico, sem mapeamento juridico especifico
  (governado pelo estado; FLAG na narrativa que falta tese canonica)

NOTA: campo pode vir COMMA-SEPARATED (string_agg de rows multiplas). Considere
o sinal mais forte na precedencia: firmado > oscilante > pendente > tese_nova
> nao_classificada.

REGRA J — TESE pro_fazenda_firmado PREVALECE SOBRE 1g FAVORAVEL:
Quando o conjunto:
  (i)   tese_jurisprudencia.resultado_majoritario contem 'pro_fazenda_firmado'
        (tese STF/STJ transitada — repetitivo/repercussao geral), AND
  (ii)  decisao_vigente 1g FAVORAVEL ao Tomador SEM transito (apelacao/agravo/
        RE/REsp pendente),
ENTAO risco_processo_intermediario = "Alto" (NAO Medio).

Por que: tese firmada vincula instancias inferiores pela ratio decidendi.
Sentenca 1g favoravel sera revertida em juizo de admissibilidade ou no
merito do recurso. Efeito suspensivo de apelacao NAO neutraliza esse risco
— apenas adia. Sem contrapeso explicito (modulacao temporal protegendo o
caso, distinguishing claro, garantia em renovacao com seguradora forte) =
Alto.

REGRA J.1 — SINAL INVERSO (tese pro_contribuinte_firmado):
'pro_contribuinte_firmado' eh vento de cauda forte (ex: PIS-COFINS Tema 69
STF). EMPURRA risco_processo_intermediario pra BAIXO mesmo se houver decisao
1g desfavoravel — reversao em instancia superior eh provavel pela mesma
ratio decidendi. Sem contrapeso explicito = Baixo.

REGRA J.2 — PENDENTE JULGAMENTO SUPERIOR:
'pendente_julgamento_superior' NAO move risco diretamente — governado pelo
estado atual da causa. Porem REDUZIR confianca em 10-20% e CITAR
EXPLICITAMENTE o julgamento pendente no estado_processual como risco
prospectivo.

REGRA J.3 — Tomador-AUTOR vs Tomador-REU (sentido invertido):
As regras J/J.1 acima assumem que sentido='favoravel' = Tomador GANHOU. Pra
classes onde Tomador eh AUTOR (Anulatoria/MS/Embargos): procedente=favoravel
ao Tomador, juris pro_contribuinte_firmado eh aliada. Pra classes onde
Tomador eh REU (EF, Cumprimento): improcedente=favoravel ao Tomador, mesma
logica via <regra_polos>.
</regra_jurisprudencia>

</regras_criticas>

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
  {apolice_block}

{tese_juris_section}{risk_decomposition_section}
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

<lembrete_final>
Antes de emitir decisao_vigente.sentido: cheque <regra_polos> no topo (Tomador
em qual polo? procedente=quem venceu?).
Extincao SEM merito em Tomador-AUTOR: ver <regra_extincao_tomador_autor> —
sentido='desfavoravel', NAO 'neutro'.
decisao_vigente.sentido NAO deve oscilar por movs procedurais recentes (REGRA G).
</lembrete_final>

Output: JSON estruturado conforme schema ProcessoSynthesisCard (enforced via
response_schema do Gemini — nao precisa formato textual no prompt). Cada campo
tem descricao especifica no Pydantic. Echo de processo_numero/classe/classe_cnj_code/
role_no_merito/tipo_judicial deste input. estado_processual eh OBRIGATORIO
(nao deixar vazio). movs_processed = {len(factsheets_capped)}.
"""

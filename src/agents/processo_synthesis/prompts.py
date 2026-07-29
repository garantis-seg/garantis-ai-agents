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

REV4 2026-06-12 (v2.3 — SEM CAP de dados, decisao Elton "nao pode ter cap de
dados em nenhum lugar"):
- _MAX_MOVS_INLINE=50 REMOVIDO dos 2 builders. Cortava as movs mais ANTIGAS
  — inclusive o card de PETICAO INICIAL (1P), que e a entrada mais antiga
  (censo 2026-06-12: 2/2 procs com card 1P tinham >50 movs = peticao nunca
  chegava ao LLM). Censo de tamanho: p99=max=2026 movs ~ 530k chars — cabe
  no contexto 1M tokens. Guard fail-loud _log_prompt_size no lugar do cap
  (loga sempre; WARN L2_PROMPT_OVERSIZE >3M chars; NUNCA trunca).
- Truncagens de render removidas (resumo_ato[:200], motivos[:80],
  resumo_dia[:200], descricao[:80], eventos[:5]).
- Instrucoes mortas de "autos raw" removidas (campos 7/8/9 + ex-REGRA F):
  o request nunca teve autos_raw_excerpt no caminho vivo — REV2 morreu
  upstream (materializer shared nao envia; schema dropa via extra-ignore).
- Instrucoes novas de leitura: PETICAO INICIAL (mov_id 'peticao-<pn>') +
  split por documento (mov_id '<id>:<doc>', regra 1-doc-maximo shared#68).
"""

import json
import logging
import os
from typing import Any

from .schemas import ApoliceContextMin, MovFactSheetMin, ProcessoSynthesisRequest


# PR7.3 (2026-05-31): _flag_enabled wrapper removido — unico caller era
# JURISPRUDENCIA_BLOCK_ENABLED do bloco interno (dropado em PR7.2).
# Provider externo jurisprudencias.ai eh single source jurisprudencial agora.

logger = logging.getLogger(__name__)

# v2.3: _MAX_MOVS_INLINE / _AUTOS_TEXT_CAP_CHARS / _DOC_TEXT_CAP_CHARS /
# _MAX_DOCS_INLINE REMOVIDOS (os 3 ultimos eram dead code desde que o
# autos_raw_excerpt morreu upstream). Sem cap de dados — ver REV4 no header.
_MOV_ID_DISPLAY_CHARS = 8       # UUID prefix na exibicao (Bug 3 handoff)

# ~Limite fisico do contexto (1M tokens ~ 4M chars) com folga pro output.
# NAO e um cap: acima disso a call falha VISIVEL no cascade (sem truncar).
_PROMPT_OVERSIZE_WARN_CHARS = 3_000_000


def _log_prompt_size(kind: str, processo_numero: str, prompt: str, movs: int) -> None:
    """Observability do sem-cap (v2.3): loga tamanho SEMPRE; WARN acima do
    threshold fisico. NUNCA trunca — principio no-silent-caps."""
    size = len(prompt)
    logger.info("L2_PROMPT_SIZE kind=%s pn=%s movs=%d chars=%d",
                kind, processo_numero, movs, size)
    if size > _PROMPT_OVERSIZE_WARN_CHARS:
        logger.warning(
            "L2_PROMPT_OVERSIZE kind=%s pn=%s movs=%d chars=%d (>%d — risco de "
            "estourar o contexto do modelo; a call falhara visivel, sem truncamento)",
            kind, processo_numero, movs, size, _PROMPT_OVERSIZE_WARN_CHARS,
        )


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


# ── Filtro de relevância p/ processo GIGANTE (2026-06-20) ──────────────────────
# L2 renderiza TODOS os cards (REV4 "sem cap"). Processo gigante (449+ cards num prompt
# só) estoura o TIMEOUT_LAYER2 de 180s — méritos 680075/680008/680046. Insight do Elton:
# o L1 JÁ classificou cada mov (relevancia_merito); o L2 não precisa RE-LER os milhares de
# movs procedurais que o L1 marcou ruido/baixa (penhora/intimação/conclusão) — não mudam
# decisao_vigente/estado/garantia. Mantém TODO sinal onde quer que esteja (NÃO é head+tail
# cego) + a cauda recente (estado corrente) + a petição inicial (não repete o bug REV4 de
# cortar a petição antiga). Só liga ACIMA do threshold → processo normal fica byte-idêntico.
# ponytail: threshold conserva o caminho quente (99% dos procs) intocado; sobe se algum
# proc de ~150-200 movs ainda estourar.
# GIANT-FILTER v2 (2026-06-25): os 2 stragglers (633163/1409966 = L2 ReadTimeout em
# giant) provaram que o filtro v1 "não reduz o bastante" — kept ainda dava centenas de
# media -> prompt enorme -> 180s. Fix (handoff giant-readtimeout + adendo): TETO DURO de
# cards renderizados (_L2_MAX_KEPT) + tail menor. Tier: HARD (nunca cortável) = decisão/
# garantia/peça-pivô/petição/suspensão/alta + cauda; SOFT = media (só preenche até o teto).
# Guardrail (adendo): o teto NUNCA evicta sinal em favor de media — hard entra inteiro
# mesmo acima do teto; media só ocupa o que sobrar. ≤200 cards continua byte-idêntico.
_L2_CARD_FILTER_THRESHOLD = 200   # <= isto: render tudo (caminho quente, sem mudança)
_L2_TAIL_KEEP = 12                # cauda recente (era 30 — reduzido no giant-filter v2)
_L2_MAX_KEPT = 50                 # teto de cards renderizados em giant (anti-180s)
_L2_HARD_REL = {"alta"}           # media saiu do hard -> vira SOFT (cortável sob o teto)


def _carrega_sinal_hard(f, is_tail: bool) -> bool:
    """Sinal que NUNCA pode ser cortado (nem pelo teto): cauda recente, decisão, evento de
    garantia, peça-pivô, petição inicial, alta relevância, OU sinal de suspensão
    (instrumento_cautelar/efeito_suspensivo — preserva o mov pra quando a suspensão
    derivada determinística aterrissar, condição A 2026-06-25)."""
    d = f.decisao or {}
    return bool(
        is_tail
        or (f.relevancia_merito in _L2_HARD_REL)
        or d.get("tem_decisao")
        or ((f.evento_garantia or {}).get("tipo") not in (None, "nenhum"))
        or (f.peca_pivo or {}).get("e_pivo")
        or str(f.mov_id or "").startswith("peticao-")
        or (d.get("instrumento_cautelar") not in (None, "nenhum"))
        or d.get("efeito_suspensivo")
    )


def _filtered_cards(factsheets_sorted: list) -> tuple[list, int]:
    """Os cards que o L2 REALMENTE renderiza: TUDO se <= threshold; senão HARD (sinal,
    sempre) + media até o teto _L2_MAX_KEPT (mais recentes). Retorna (kept, n_omit). FONTE
    ÚNICA do filtro — usada pelo render E pelo detector de chunk (mesmo conjunto). O teto
    nunca corta HARD: se houver mais sinal que o teto, kept passa do teto (segurança > custo)."""
    n = len(factsheets_sorted)
    if n <= _L2_CARD_FILTER_THRESHOLD:
        return list(factsheets_sorted), 0
    tail_start = n - _L2_TAIL_KEEP
    hard_idx, soft_idx = [], []
    for i, f in enumerate(factsheets_sorted):
        if _carrega_sinal_hard(f, i >= tail_start):
            hard_idx.append(i)
        elif f.relevancia_merito == "media":
            soft_idx.append(i)
    room = max(0, _L2_MAX_KEPT - len(hard_idx))
    keep_idx = set(hard_idx) | set(soft_idx[-room:] if room else [])  # media: as mais recentes
    kept = [factsheets_sorted[i] for i in sorted(keep_idx)]
    return kept, n - len(kept)


def _render_timeline(factsheets_sorted: list, empty: str) -> str:
    """Timeline pro prompt L2. Processo normal (<= threshold): render TUDO (REV4 intacto).
    Processo gigante: filtra pelo sinal que o L1 já computou + marcador dos omitidos (no
    silent cap). Bound determinístico que evita o TIMEOUT_LAYER2 sem cortar sinal."""
    kept, n_omit = _filtered_cards(factsheets_sorted)
    block = "\n  ".join(_summarize_factsheet(f) for f in kept) or empty
    if n_omit:
        block += (
            f"\n  [+{n_omit} movs omitidas (de {len(factsheets_sorted)} no total) — processo gigante: "
            "L1 marcou ruido/baixa (penhora/intimacao/conclusao/expediente) + media excedente ao teto; "
            "nao alteram decisao_vigente/estado/garantia. PRESERVADO inteiro: decisoes, eventos de "
            "garantia, peca-pivo, peticao inicial, sinais de suspensao e as movs mais recentes.]"
        )
    return block


def build_probabilidade_exito_prompt(req: ProcessoSynthesisRequest) -> str:
    """Prompt FOCADO so na Probabilidade de Exito Daycoval — call B do C2.

    Sem ruido das outras partes (estado_processual, decisao_vigente, etc.) —
    LLM concentra atencao na matriz e produz output mais consistente.
    Empirico v1: combinado com synthesis no mesmo prompt, gemini-2.5-flash
    omitia prob_exito em 100% das tentativas (smoke 1-merito 12151 + 50).
    """
    factsheets = req.mov_factsheets or []
    # MESMA chave (data ASC, mov_id ASC) do build_processo_synthesis_prompt e do
    # split_movs_chronological — as 3 ordens batem (determinismo; review 2026-06-22).
    factsheets_sorted = sorted(factsheets, key=lambda f: (f.data or "", f.mov_id or ""))

    # Render tudo p/ processo normal (REV4); filtra ruido/baixa só p/ processo gigante.
    timeline_block = _render_timeline(factsheets_sorted, "(sem movimentacoes)")

    matriz_block = _build_matriz_block(req.tipo_judicial)

    header_parts = [f"CNJ: {req.processo_numero}"]
    if req.classe:
        header_parts.append(f"Classe: {req.classe}")
    header_parts.append(f"Tipo judicial: {req.tipo_judicial.upper()}")
    if req.polo_passivo:
        header_parts.append(f"Tomador (polo passivo): {req.polo_passivo}")
    header_block = "\n  ".join(header_parts)

    prompt = f"""Voce e analista juridico brasileiro especializado em SEGURO GARANTIA JUDICIAL.

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
    _log_prompt_size("prob_exito", req.processo_numero, prompt, len(factsheets_sorted))
    return prompt


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
        parts.append(fs.resumo_ato)

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
        parts.append(f"DELTA_RISCO:{dr.get('direcao')} ({dr.get('motivo') or ''})")

    pivo = fs.peca_pivo or {}
    if pivo.get("e_pivo"):
        parts.append(f"PIVO ({pivo.get('motivo') or ''})")

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
    # VERMELHO na v_policy_validity_traffic_light e `termination_date < CURRENT_DATE`:
    # apolice EXPIRADA (nao "vencendo") -> nao cobre. Whitelist nos demais de proposito:
    # farol desconhecido/indeterminado nao vira afirmacao de vigencia.
    farol = (ap.vigencia_farol or "").strip().lower()
    if farol == "vermelho":
        parts.append(f"VENCIDA em {ap.vigencia_termino}" if ap.vigencia_termino else "VENCIDA")
    elif farol in ("verde", "amarelo", "laranja") and ap.vigencia_termino:
        parts.append(f"vigente ate {ap.vigencia_termino}")
    if ap.is_central_for_merito:
        parts.append("(central no merito)")
    return " | ".join(parts)


# _summarize_day_factsheet REMOVIDO em 2026-06-13 (onda 2 do teardown do
# tier por-dia): day_factsheets sairam do payload/prompt do L2. Sem bump de
# PROMPT_VERSION de proposito — pra todo proc o bloco ja renderizava o
# placeholder vazio (cards day 100% supersedidos antes deste deploy).


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


def _clip_head_tail(text: str, *, head: int, tail: int) -> str:
    """Clip preservando inicio (materia/tese) + fim (dispositivo) da ementa.

    O dispositivo (provido/improvido/nega-se) — o sinal de QUEM GANHOU — costuma
    vir no FIM da ementa. Truncar so o head (bug pre-2026-06-21: cap 300 chars no
    head) jogava o resultado fora. Se cabe inteiro (<= head+tail) retorna intacto.
    """
    text = text or ""
    if len(text) <= head + tail:
        return text
    return f"{text[:head]} […] {text[-tail:]}"


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
            # O DISPOSITIVO (provido/improvido — quem ganhou) vem no FIM da ementa;
            # cap-no-head jogava o resultado fora. head+tail preserva materia +
            # dispositivo. Provider devolve ~600-900 chars => na pratica entra
            # inteira; head+tail so morde outlier longo.
            excerpt = _clip_head_tail(excerpt, head=700, tail=400)
            lines.append(f"    [{i}] {pn} ({pub}): {excerpt}")
    else:
        lines.append("  (sem ementas retornadas pelo provider)")
    return "\n".join(lines)


def build_processo_synthesis_prompt(req: ProcessoSynthesisRequest) -> str:
    """Build prompt que agrega mov_factsheets + apolice context.

    Sort do timeline e DETERMINISTICO: (data ASC, mov_id ASC). mov_id e
    cluster_id UUID estavel pos-Fase 2 (Bug 3 handoff). Mesmo input
    produz mesmo prompt entre cascades — drift L2 eliminado.

    v2.3: SEM CAP de movs (REV4 no header) — a peticao 1P (entrada mais
    antiga) e movs historicas sempre entram. Guard fail-loud no retorno.
    """
    factsheets = req.mov_factsheets or []
    factsheets_sorted = sorted(
        factsheets,
        key=lambda f: (f.data or "", f.mov_id or ""),
    )

    timeline_block = _render_timeline(factsheets_sorted, "(sem movimentacoes mov-by-mov)")

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
    # §3.2 (2026-06-21): o bloco <regra_jurisprudencia> (glossario 6-valores
    # pro_contribuinte_firmado/.../nao_classificada + regras J/J.1/J.2/J.3) tambem
    # foi removido das <regras_criticas> — operava no MESMO campo morto
    # tese_jurisprudencia e empurrava o LEGACY risco_processo_intermediario. A juris
    # VIVA entra so via risk_decomposition_section (risco_jurisprudencial, 4 valores
    # do provider). Sistema unico, sem double-count nem glossario fantasma.
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
        "                          IGNORE estado processual. LEIA AS EMENTAS — cada uma\n"
        "                          traz o dispositivo (provido/improvido/nega-se) que diz\n"
        "                          QUEM GANHOU. VOCE determina a tendencia da tese a partir\n"
        "                          das EMENTAS. O campo 'resultado=' eh uma heuristica\n"
        "                          regex AUXILIAR (dica, NAO veredito) — se as ementas\n"
        "                          contradizem o 'resultado=', confie nas EMENTAS.\n"
        "                          Quando NAO ha sinal forte (ementas divergentes, sem\n"
        "                          mapeamento de tese, n_hits<3), emit 'Indeterminado' —\n"
        "                          NUNCA chute Baixo por default.\n"
        "                          Definida a tendencia, mapeie pro bucket de risco:\n"
        "                            pro_contribuinte (tomador/executado vence) -> Baixo\n"
        "                            pro_fazenda (fisco vence)                  -> Alto\n"
        "                            dividida / oscilante                       -> Medio\n"
        "                            sem sinal                                  -> Indeterminado\n"
        "  AMBOS sao orthogonal — NAO combine sinais cruzados. Camada 3 agrega via\n"
        "  matriz determ + A/B test entre prompts (PR6).\n"
        "  risco_processo_intermediario LEGACY tambem eh emitido (compat backward).\n"
    )

    prompt = f"""Voce e analista juridico-securitario brasileiro especializado em SEGURO GARANTIA JUDICIAL.

Sua tarefa: sintetizar o estado atual do PROCESSO a partir dos FACTSHEETS da Camada 1
(mov_factsheet) + contexto da(s) apolice(s).
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

CAVEAT — decisao.sentido dos factsheets vem de derivacao DETERMINISTICA
on-read (truth-table por parte seguravel) e GATEIA (null) quando o lado nao
e identificavel com confianca. sentido=null NAO significa decisao neutra —
releia natureza + resumo com a lente de polo acima e derive o sentido voce
mesmo em decisao_vigente. Se um sentido derivado contradisser sua leitura de
polo (ex: 'desfavoravel' em Anulatoria procedente onde Tomador e autor),
prevalece SUA leitura — corrija em estado_processual + decisao_vigente.sentido.
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

</regras_criticas>

=== PROCESSO ===
  {header_block}

=== TIMELINE DE FACTSHEETS (mov_factsheets, ordenados por data ASC) ===
  {timeline_block}

  INSTRUCOES PARA a entrada de PETICAO INICIAL (quando presente):
  - A entrada com mov_id 'peticao-<numero>' (categoria=peticao, inicio da
    timeline) e a PETICAO INICIAL: tese + pedido do autor extraidos da peca
    inaugural. NAO e ato decisorio nem movimentacao nova.
  - Use-a pra: (a) ancorar a REGRA DE POLOS (quem moveu a acao e o que
    pede); (b) contexto da causa no estado_processual; (c) evento de
    garantia OFERTADA na inicial (quando presente).
  - Ela NUNCA entra em decisao_vigente.

  INSTRUCAO PARA entradas de SPLIT POR DOCUMENTO:
  - Entradas com mov_id no formato '<id>:<doc>' sao DOCUMENTOS distintos da
    MESMA movimentacao (split 1-doc-por-unidade). NAO conte como atos
    processuais separados.

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
   Interlocutorias RECENTES de mero impulso (conclusao, despacho, penhora online,
   bloqueio, novo prazo) NAO substituem decisao de merito anterior — elas
   apenas MODULAM o estado_processual. Reflete-as em estado_processual com
   contexto, mas mantenha decisao_vigente ancorada na ultima decisao de merito.
   (Suspensao/sobrestamento NAO sao "mero impulso" e NAO entram nesta lista —
   ver REGRA DE SUSPENSAO E TRANSITO abaixo: podem MOVER a decisao_vigente.)

   REGRA DE SUSPENSAO E TRANSITO (distincao MERITO-vs-EXECUCAO — OBRIGATORIA antes
   de cravar transito_certificado=true): nem toda suspensao e ruido procedural.
   Classifique a suspensao / sobrestamento / reabertura MAIS RECENTE:
   - SUSPENSAO ou REABERTURA DE MERITO -> o merito NAO e final -> transito_certificado=FALSE
     e a decisao de merito antiga NAO transitou: sobrestamento por IRDR / Tema repetitivo /
     repercussao geral / recurso de merito (REsp/RE/RR) ainda PENDENTE de julgamento;
     decisao de merito ANULADA; revogacao-da-suspensao ou desarquivamento que REATIVA a
     discussao. Aqui o processo voltou a discutir o merito — NAO certifique transito mesmo
     que exista sentenca/acordao adverso antigo; ancore a decisao_vigente no estado reaberto.
   - SUSPENSAO DE EXECUCAO POS-TRANSITO -> o merito JA transitou; a suspensao so pausa a
     COBRANCA -> transito_certificado PERMANECE true: Acao Rescisoria em tramite, Recuperacao
     Judicial do devedor, parcelamento/transacao de divida ja transitada. Uma Acao Rescisoria
     so existe PORQUE o processo ja transitou — NAO rebaixe o transito por causa dela.
   DESEMPATE: se ha certidao/mov de TRANSITO EM JULGADO ANTERIOR a suspensao e a suspensao e
   da EXECUCAO (rescisoria / RJ / parcelamento), MANTENHA transito=true; se a suspensao precede
   a finalidade ou REABRE o merito (IRDR / anulacao / reativacao), transito_certificado=false.
   CUMPRIMENTO ou EXECUCAO DE SENTENCA nao e decisao de merito NOVA — e a fase de cobranca de
   uma decisao ja existente; NAO o use como decisao_vigente nem como prova de transito.

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
   - transito_certificado: true SO se ha mov certificando transito E nao ha
     suspensao-de-merito / anulacao / reabertura POSTERIOR (REGRA DE SUSPENSAO E
     TRANSITO). Suspensao-de-execucao-pos-transito (rescisoria/RJ) MANTEM true.
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

7. valor_em_disputa (BRL): melhor estimativa dos factsheets. Use o mais
   recente/maior entre valor_causa e valor_debito_executado. null se nenhum disponivel.

8. valor_garantia (BRL): valor da apolice/garantia. Use prioritariamente o apolice card
   (apolices[].valor_is). Se nao, valores.valor_garantia dos factsheets.

9. confianca (0.0-1.0): quanto voce confia na sintese. Use 0.85+ quando ha decisao clara
   (factsheet com tem_decisao=true), 0.6-0.8 quando o estado e ambiguo, < 0.5 quando
   muitos factsheets vazios.

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

F. ESTABILIDADE TEMPORAL — decisao_vigente NAO deve oscilar entre cuts/snapshots
   sucessivos do MESMO processo so porque chegaram movs procedurais novos.
   (EXCECAO: suspensao-de-merito / anulacao / reativacao NAO sao "procedurais" —
   elas DEVEM mover a decisao_vigente e zerar transito; ver REGRA DE SUSPENSAO E TRANSITO.)
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
decisao_vigente.sentido NAO deve oscilar por movs procedurais recentes (REGRA F).
Antes de transito_certificado=true: houve suspensao-de-merito / anulacao / reativacao
DEPOIS da decisao? Se sim, transito=false (REGRA DE SUSPENSAO E TRANSITO). Suspensao-de-
execucao-pos-transito (Acao Rescisoria / Recuperacao Judicial) MANTEM transito=true.
</lembrete_final>

Output: JSON estruturado conforme schema ProcessoSynthesisCard (enforced via
response_schema do Gemini — nao precisa formato textual no prompt). Cada campo
tem descricao especifica no Pydantic. Echo de processo_numero/classe/classe_cnj_code/
role_no_merito/tipo_judicial deste input. estado_processual eh OBRIGATORIO
(nao deixar vazio). movs_processed = {len(factsheets_sorted)}.
"""
    _log_prompt_size("synthesis", req.processo_numero, prompt, len(factsheets_sorted))
    return prompt

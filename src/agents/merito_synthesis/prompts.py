"""Prompt pro merito_synthesis agent (engine v6_meritos camada 3).

Output PRIMARIO da engine - risco + justificativa por merito.

Estrutura modular: blocos COMUNS (intro, glossario, cards, etc.) + blocos
PLUGAVEIS dispatch por `tipo_judicial` dominante (fiscal/trabalhista/civel/
misto). Routing determ. via `_determine_tipo_dominante()` com threshold 80%
pra escolher variant; abaixo disso cai pra 'misto' (fallback generico com
confidence reduzido).

Padrao arquitetural: ver memory `engine-v6-prompt-modular-pattern`.
"""

import json
import os
from collections import Counter
from typing import Literal

from .schemas import (
    AIIMCardMin,
    CDACardMin,
    JurisprudenciaMin,
    MeritoSynthesisRequest,
    ParadigmaMin,
    PreviousSnapshot,
    ProcessoSynthesisMin,
    TomadorCardMin,
)


from .._utils import flag_enabled as _flag_enabled_shared


def _flag_enabled(name: str, default: str = "true") -> bool:
    """Wrapper backward-compat com default ON pros flags E4-E7.

    Helper canonical é `agents._utils.flag_enabled` (default OFF). Este wrapper
    preserva o default ON usado nos flags Sprint 2 P&P.
    """
    return _flag_enabled_shared(name, default=default)


# Bump quando alterar build_merito_synthesis_prompt OU MeritoSynthesisCard
# schema. Sufixo `-{tipo}` via _prompt_version_for() rastreia variant em
# leads.engine_llm_calls.
#
# v2.1 (2026-05-25, P1+P2 do prompt-engineering FINDINGS):
#   - Reativado response_schema=MeritoSynthesisCard em agent.py (depois que
#     schema foi reformatado pra eliminar dict[str, Any] que causava
#     additionalProperties bug). BreakdownProcesso + CardsIndexCount substituem
#     legacy dict.
#   - Optional[str] enum apertados pra Literal[...] strict (lição L2 v2.1 —
#     evita loop infinito do decoder Gemini com response_schema).
#   - Removido bloco _build_output_schema (=== FORMATO DE SAIDA ===) — Output
#     enforced via response_schema nativo. Enriquecidas Field(description) em
#     schemas.py com semantica que vivia no prompt (risco, justificativa, etc).
#   - L3 ja tinha _build_glossary_roles + _build_consistency_check NO TOPO —
#     ordem ja seguia a metodologia P2. Adicionado _build_lembrete_final como
#     recency anchor pras 3 regras criticas.
#
# v2.2 (2026-05-25, proposta L2-only jurisprudencia):
#   - Jurisprudencia MIGRADA pra L2 (Opcao A: single source of truth).
#   - Removido bloco _build_jurisprudencia_block do prompt.
#   - Regras G/G.1/G.2 (que aplicavam juris hard) REMOVIDAS dos 4 variants
#     _build_regras_ouro_{fiscal,trab,civel,misto}. L3 confia 100% em
#     risco_processo_intermediario do L2 (que ja absorveu juris via
#     regras J/J.1/J.2 do L2 prompt v2.2).
#   - Removido `jurisprudencia` do MeritoSynthesisRequest (schema).
#   - Paradigmas (_build_paradigmas_block) MANTIDOS — sao contexto NARRATIVO
#     pra defender risco vs cliente cetico, nao regra de decisao.
#   - Elimina double-counting: jurisprudencia pesava 2x (Matriz Daycoval
#     implicito em L2 + regras G em L3).
PROMPT_VERSION_BASE = "merito_synthesis.v2.4"


def _prompt_version_for(tipo: str) -> str:
    """Concatena base + tipo dominante p/ telemetria.

    Strings produzidas:
      merito_synthesis.v1.1-fiscal
      merito_synthesis.v1.1-trabalhista
      merito_synthesis.v1.1-civel
      merito_synthesis.v1.1-misto

    Backward-compat queries:
      WHERE prompt_version LIKE 'merito_synthesis.v1.1-%'  (apenas split)
      WHERE prompt_version LIKE 'merito_synthesis.v1.%'    (todas versoes)
    """
    return f"{PROMPT_VERSION_BASE}-{tipo}"


# ─── Card summarizers (input cards → string fragments) ─────────────────────


def _summarize_processo_synthesis(ps: ProcessoSynthesisMin) -> str:
    """Bloco de 1 processo_synthesis pro prompt."""
    parts = [f"=== PROCESSO {ps.processo_numero}"]
    if ps.role_no_merito:
        parts[0] += f" ({ps.role_no_merito})"
    if ps.classe:
        parts.append(f"  Classe: {ps.classe}")
    if ps.tipo_judicial:
        parts.append(f"  Tipo: {ps.tipo_judicial}")
    pe = ps.probabilidade_exito or {}
    if pe.get("classificacao"):
        prob_str = f"  Prob. Exito (Daycoval): {pe['classificacao']} (score={pe.get('score')})"
        if pe.get("justificativa"):
            prob_str += f" — {(pe['justificativa'] or '')[:140]}"
        parts.append(prob_str)
        if pe.get("criterios_aplicados"):
            for c in (pe["criterios_aplicados"] or [])[:2]:
                parts.append(f"    crit: {c[:160]}")
    if ps.estado_processual:
        parts.append(f"  Estado: {ps.estado_processual}")
    dv = ps.decisao_vigente or {}
    if dv.get("sentido") or dv.get("natureza"):
        parts.append(
            f"  Decisao vigente: {dv.get('natureza') or '?'} "
            f"({dv.get('sentido') or '?'}, instancia={dv.get('instancia') or '?'}, "
            f"data={dv.get('data') or '?'}, transito={dv.get('transito_certificado')}, "
            f"recorrida={dv.get('recorrida')})"
        )
    if ps.risco_processo_intermediario:
        parts.append(f"  Risco intermediario: {ps.risco_processo_intermediario}")
    if ps.trajetoria_dentro_processo and ps.trajetoria_dentro_processo != "indefinida":
        parts.append(f"  Trajetoria interna: {ps.trajetoria_dentro_processo}")
    pivo = ps.peca_pivo_candidata or {}
    if pivo.get("mov_id"):
        parts.append(f"  Peca-pivo candidata: mov_id={pivo['mov_id']} ({(pivo.get('motivo') or '')[:120]})")
    lc = ps.lifecycle_garantia or []
    if lc:
        parts.append(f"  Lifecycle garantia ({len(lc)} eventos):")
        for ev in lc[:5]:
            parts.append(
                f"    {ev.get('data') or '?'} | {ev.get('evento')} "
                f"({ev.get('tipo_garantia') or 'na'}) -> {ev.get('status_pos')}"
            )
    val_parts = []
    if ps.valor_em_disputa:
        val_parts.append(f"em_disputa=R$ {ps.valor_em_disputa:,.0f}".replace(",", "."))
    if ps.valor_garantia:
        val_parts.append(f"garantia=R$ {ps.valor_garantia:,.0f}".replace(",", "."))
    if val_parts:
        parts.append(f"  Valores: {', '.join(val_parts)}")
    return "\n".join(parts)


def _summarize_cda(cda: CDACardMin) -> str:
    parts = [f"  CDA {cda.cda_number or '?'}"]
    if cda.tipo_tributo:
        parts.append(cda.tipo_tributo)
    if cda.ente:
        parts.append(cda.ente)
    if cda.valor:
        parts.append(f"R$ {cda.valor:,.0f}".replace(",", "."))
    if cda.aiim_number_associado:
        parts.append(f"AIIM:{cda.aiim_number_associado}")
    if cda.notes:
        parts.append((cda.notes or "")[:120])
    return " | ".join(parts)


def _summarize_aiim(aiim: AIIMCardMin) -> str:
    parts = [f"  {aiim.tipo or 'AIIM'} {aiim.numero or '?'}"]
    if aiim.relacao:
        parts.append(f"relacao: {aiim.relacao}")
    if aiim.contexto_snippet:
        parts.append((aiim.contexto_snippet or "")[:200])
    return " | ".join(parts)


def _summarize_tomador(tom: TomadorCardMin) -> str:
    parts = [f"  Tomador: {tom.nome or tom.cnpj_basico or '?'}"]
    h = tom.historico or {}
    if h.get("rj_atual"):
        parts.append("RJ atual = TRUE")
    if h.get("total_processos_vivos"):
        parts.append(f"{h['total_processos_vivos']} processos vivos")
    if h.get("total_apolices_ativas"):
        parts.append(f"{h['total_apolices_ativas']} apolices ativas")
    if h.get("taxa_apolice_recusada") is not None:
        parts.append(f"taxa recusa {h['taxa_apolice_recusada']:.0%}")
    if h.get("taxa_descumprimento_acordo") is not None:
        parts.append(f"taxa descumprimento {h['taxa_descumprimento_acordo']:.0%}")
    if tom.alertas:
        parts.append("ALERTAS: " + ", ".join(tom.alertas))
    return " | ".join(parts)


def _summarize_jurisprudencia(jur: JurisprudenciaMin) -> str:
    parts = []
    if jur.tese_nome:
        parts.append(f"Tese: {jur.tese_nome}")
    if jur.tema_stj:
        parts.append(f"STJ Tema {jur.tema_stj}")
    if jur.tema_stf:
        parts.append(f"STF {jur.tema_stf}")
    if jur.resultado_majoritario:
        parts.append(f"resultado majoritario: {jur.resultado_majoritario}")
    return " | ".join(parts) if parts else "(sem mapeamento de jurisprudencia)"


def _summarize_previous(prev: PreviousSnapshot | None) -> str:
    if not prev or not prev.risco_anterior:
        return "PRIMEIRA CLASSIFICACAO (sem snapshot anterior)"
    parts = [f"  risco_anterior: {prev.risco_anterior}"]
    if prev.classified_at_anterior:
        # Bug 4 followup: truncate pra YYYY-MM-DD (data so, sem horario).
        # Cada cascade nova ve um snapshot anterior gerado pela cascade
        # imediatamente previa — hora/min/seg variam entre runs no mesmo dia
        # e poluem L3 prompt_hash sem agregar sinal util ao LLM (granularidade
        # de "dia" basta p/ avaliar staleness do snapshot prev vs hoje).
        cls_at = str(prev.classified_at_anterior)[:10]
        parts.append(f"classified_at: {cls_at}")
    if prev.decisao_anterior:
        parts.append(f"decisao_anterior: {json.dumps(prev.decisao_anterior, ensure_ascii=False)[:200]}")
    return "\n".join(parts)


# ─── Routing (axis: tipo_judicial dominante) ───────────────────────────────


def _determine_tipo_dominante(
    processo_syntheses: list[ProcessoSynthesisMin],
) -> Literal["fiscal", "trabalhista", "civel", "misto"]:
    """Determina tipo_judicial dominante do merito.

    Threshold 80%: o tipo mais comum precisa cobrir >=80% dos processos
    com tipo nao-NULL pra ser eleito 'dominante'. Abaixo disso retorna
    'misto' (fallback generico).

    Retorna 'misto' quando:
    - processo_syntheses vazio
    - todos tipos NULL (sinal nao disponivel pra dispatch determ.)
    - tipo mais comum cobre <80% dos processos

    Tie-breaking: Counter.most_common(1) usa ordem de insercao pra empate.
    Empates 50/50 entre 2 tipos -> sempre <80% -> 'misto'.
    """
    if not processo_syntheses:
        return "misto"
    tipos = [p.tipo_judicial for p in processo_syntheses if p.tipo_judicial]
    if not tipos:
        return "misto"
    counter = Counter(tipos)
    most_common, count = counter.most_common(1)[0]
    if count / len(tipos) >= 0.8:
        return most_common  # type: ignore[return-value]
    return "misto"


# ─── Common prompt blocks (no axis variation) ──────────────────────────────


def _build_intro() -> str:
    """Apresentacao do papel + tarefa. Comum a todos os tipos."""
    return (
        "Voce e analista juridico-securitario brasileiro especializado em SEGURO GARANTIA JUDICIAL.\n"
        "\n"
        "Sua tarefa: classificar o RISCO DE ACIONAMENTO DA APOLICE pro MERITO inteiro. Voce recebe\n"
        "os processo_syntheses (camada 2 ja sintetizou cada processo) + tomador + cda/aiim\n"
        "+ jurisprudencia da tese + snapshot anterior (referencia historica).\n"
        "\n"
        "ESTA E A CAMADA 3 - OUTPUT PRIMARIO. Risco aqui e o que vai pra UI/cliente."
    )


def _build_glossary_roles() -> str:
    """Glossario Tomador/Segurado/Garantido + REGRA DURA 3-step. Comum.

    Bug 5a handoff: glossario fixo elimina oscilacao Tomador/Segurado entre
    cascades. Terminologia e a mesma em fiscal/trabalhista/civel — soh muda
    quem ocupa cada papel (em fiscal Tomador=contribuinte, em trabalhista
    Tomador=empregador, em civel Tomador=devedor)."""
    return """=== GLOSSARIO ROLES EM SEGURO GARANTIA JUDICIAL (LEIA ANTES DE CLASSIFICAR) ===

- Tomador: quem contrata o seguro (paga premio). Em execucao fiscal = contribuinte/devedor.
- Segurado/Garantido: beneficiario (recebe se Tomador inadimplir). Em execucao fiscal = Fazenda Publica.
- Sentenca FAVORAVEL ao Tomador (procedente p/ contribuinte) -> Tomador ganhou -> BAIXO risco pro seguro.
- Sentenca DESFAVORAVEL ao Tomador (improcedente p/ contribuinte) -> Tomador perdeu -> ALTO risco pro seguro.
- "Sentenca procedente" SEM contexto: identificar PEDIDO antes de classificar. Quem pediu? Quem ganhou?
- Recurso pendente NAO neutraliza desfavoravel: ALTO permanece ate transito FAVORAVEL ao Tomador.

REGRA DURA: antes de redigir justificativa, identifique de forma explicita:
  (a) quem e o Tomador no merito (consultar bloco TOMADOR);
  (b) quem ganhou na ultima decisao_vigente (consultar processo_syntheses);
  (c) se "(a) == (b)" -> tendencia BAIXO; se "(a) != (b)" -> tendencia ALTO.
NUNCA usar "Garantido" e "Tomador" como sinonimos. NUNCA inverter "favoravel/desfavoravel"
na narrativa (se a decisao foi DESFAVORAVEL ao Tomador, NAO escrever "sentenca favoravel ao
Banco Mercantil" quando o Banco e o Tomador)."""


def _build_consistency_check() -> str:
    """Bug 5c handoff: check obrigatorio pro-Alto/pro-Baixo. Comum a todos."""
    return """=== CONSISTENCY CHECK (obrigatorio antes de emitir output) ===

1. Releia o que voce escreveu em `probabilidade_exito_merito.contribuicao_no_risco`,
   `justificativa` e `narrativa_executiva`.

2. Se QUALQUER um desses campos contem frases pro-Alto como:
   - "empurra o risco para Alto" / "Altissimo" / "para cima"
   - "alta chance de reversao desfavoravel ao Tomador"
   - "alta probabilidade de reversao" (mesmo sem dizer "Alto")
   - "elevando o risco de acionamento da apolice"
   - "probabilidade remota de exito" / "probabilidade de exito e 'remota'"
   - "jurisprudencia desfavoravel a tese / contraria ao Tomador"
   - "tendencia de perda em instancias superiores"
   - "tese majoritariamente pro_fazenda" / "majoritario pro-Fazenda"
   - "tese firmada / consolidada / decidida contra o Tomador" no STF/STJ/repetitivo

   ENTAO o campo `risco` final DEVE ser "Alto" OU "Altissimo". NUNCA Medio ou Baixo
   quando os argumentos escritos vao pro Alto.

3. Reverso simetrico: se argumentos sao pro-Baixo (Tomador ganhou + transito
   FAVORAVEL + tese pro_contribuinte + garantia ativa sem disputa), risco NAO
   pode ser Medio nem Alto. Deve ser "Baixo".

4. Se voce esta inclinado a atribuir Medio APESAR de argumentos pro-Alto na
   redacao, voce tem 2 opcoes (NUNCA contradicao silenciosa):
   - OPCAO A: reescreva justificativa/contribuicao_no_risco/narrativa
     EXPLICITANDO os contrapesos que justificam Medio (ex: "garantia em
     renovacao com seguradora forte", "tomador com historico solido de
     liquidez", "prazo longo ate transito permitindo recomposicao",
     "1g consolidada favoravel ao Tomador pesa contra reversao automatica
     pela jurisprudencia superior").
   - OPCAO B: eleve risco final pra "Alto" (mais honesto que negar a
     argumentacao escrita).

5. Medio e veredict LEGITIMO somente quando a narrativa o sustenta com
   contrapesos explicitos. NAO use Medio como "tom medio cauteloso" — isso
   destroi a confianca na narrativa quando o leitor vai conferir e ve
   "argumentei Alto mas atribui Medio".

Esta regra existe porque cascades anteriores (m=3 snapshot 319) produziram
contradicoes do tipo: contribuicao_no_risco diz "empurra para Alto" +
justificativa diz "elevando o risco" + risco final = Medio. NAO emita output
nesse padrao — releia, ajuste narrativa OU eleve risco."""


def _build_merito_header_block(req: MeritoSynthesisRequest) -> str:
    """MERITO ID + titulo + CNPJ + razao social. Comum a todos."""
    header_lines = [f"MERITO ID: {req.merito_id} (context={req.merito_context})"]
    if req.titulo:
        header_lines.append(f"Titulo: {req.titulo}")
    if req.tipo_principal:
        header_lines.append(f"Tipo principal: {req.tipo_principal}")
    if req.cnpj_principal:
        header_lines.append(f"CNPJ: {req.cnpj_principal}")
    if req.razao_social:
        header_lines.append(f"Razao social: {req.razao_social}")
    header_block = "\n  ".join(header_lines)
    return f"=== MERITO ===\n  {header_block}"


def _build_processos_block(req: MeritoSynthesisRequest) -> str:
    """Synthesis cards dos processos do merito (chama _summarize_processo_synthesis)."""
    if req.processo_syntheses:
        proc_block = "\n\n".join(_summarize_processo_synthesis(p) for p in req.processo_syntheses)
    else:
        proc_block = "(SEM processo_synthesis disponivel - merito vazio ou cards faltam)"
    return f"=== PROCESSOS DO MERITO (synthesis cards) ===\n{proc_block}"


def _build_cdas_block(req: MeritoSynthesisRequest) -> str:
    cdas_block = "\n".join(_summarize_cda(c) for c in (req.cdas or [])) or "  (sem CDA materializada)"
    return f"=== CDA / DIVIDAS ATIVAS ===\n{cdas_block}"


def _build_aiims_block(req: MeritoSynthesisRequest) -> str:
    aiims_block = "\n".join(_summarize_aiim(a) for a in (req.aiims or [])) or "  (sem AIIM/PAF materializado)"
    return f"=== AIIM / PAFs ADMINISTRATIVOS ===\n{aiims_block}"


def _build_tomador_block_section(req: MeritoSynthesisRequest) -> str:
    tomador_block = _summarize_tomador(req.tomador) if req.tomador else "  (sem tomador card)"
    return f"=== TOMADOR (historico CNPJ basico) ===\n{tomador_block}"


def _build_jurisprudencia_block(req: MeritoSynthesisRequest) -> str:
    """DEPRECATED v2.2: jurisprudencia migrada pra L2 (proposta L2-only).
    Funcao mantida pra backward-compat de imports. Retorna string vazia —
    suprimida do prompt no `build_prompt_and_version`."""
    return ""


def _build_snapshot_anterior_block(req: MeritoSynthesisRequest) -> str:
    prev_block = _summarize_previous(req.previous_snapshot)
    return f"=== SNAPSHOT ANTERIOR (referencia historica — engine v6 nao usa hoje pra trajetoria; informativo) ===\n{prev_block}"


def _format_paradigma(p: ParadigmaMin) -> str:
    """Formato: '{tribunal} {instancia} ({data}) - {sentido} - {ementa[:200]} | Rel. {relator}'."""
    ementa = (p.ementa_resumo or "")[:200] or "(sem ementa)"
    chunks = [p.tribunal or "?"]
    if p.instancia:
        chunks.append(p.instancia)
    if p.data_decisao:
        chunks.append(f"({p.data_decisao})")
    chunks.append("-")
    chunks.append(p.sentido or "?")
    chunks.append("-")
    chunks.append(ementa)
    if p.relator:
        chunks.append(f"| Rel. {p.relator}")
    return "  - " + " ".join(chunks)


def _build_paradigmas_block(req: MeritoSynthesisRequest) -> str:
    """Acordaos/sentencas firmes da tese (ref.tese_decisao_individual WHERE
    eh_paradigma=TRUE).

    Pre-filtrados por tese_canonica_id — tipo-consistent (tese determina tipo
    judicial), entao mesmo bloco vale pra todas as variants fiscal/trab/civel.
    Quando vazio (tese sem paradigmas curados), retorna '' e bloco eh suprimido
    no join. Asymetrico vs outros _build_*_block (que renderizam '(sem X)'
    placeholder) — paradigmas eh prompt-only e nao informativo quando vazio,
    so polui contexto.

    Flag E7 PARADIGMAS_BLOCK_ENABLED (default ON): set false pra desligar
    o bloco em A/B test sem code change."""
    if not _flag_enabled("PARADIGMAS_BLOCK_ENABLED"):
        return ""
    if not req.paradigmas:
        return ""
    lines = ["=== DECISOES PARADIGMA DESTA TESE ==="]
    lines.extend(_format_paradigma(p) for p in req.paradigmas)
    return "\n".join(lines)


def _build_protocolo_postura_default() -> str:
    """POSTURA + DEFAULT Baixo. Comum a todos os tipos.

    "Medio" NUNCA como zona-cinza — regra vale pra todos os tipos."""
    return """=== PROTOCOLO DE RISCO BASE (CRITICA — leia antes de classificar risco) ===

POSTURA: o gatilho de acionamento da apolice de seguro garantia eh a
EXIGENCIA ATIVA de pagamento ao Tomador (intimacao pra pagar, penhora,
levantamento, cumprimento de sentenca). Sem gatilho concreto, NAO HA risco
imediato.

DEFAULT = "Baixo". So sobe pra Medio/Alto/Altissimo com SINAL EXPLICITO
documentado nos cards. NUNCA usar "Medio" como zona-cinza/cauteloso."""


def _build_templates_poletto() -> str:
    """TEMPLATES POLETTO canonicos — classificacao TEMPLATE-FIRST.

    Adicionado v2.3 apos analise side-by-side de 83 justificativas unicas
    Poletto (124 Baixo + 56 Medio + 55 Alto + 3 Altissimo) revelar que o
    time Poletto classifica por TEMPLATES estruturais 2-D:
    eixo 1 = fase processual (sem sentenca -> sentenca -> 2g -> transito ->
    intimacao seguradora); eixo 2 = direcao (favoravel/desfavoravel Tomador).

    L3 estava fazendo raciocinio livre sobre detalhes isolados (termo
    penhora, prob_exito=remota, interlocutoria) e perdendo o TEMPLATE
    estrutural. Pilot 30 acc 20% sem template lookup.

    Estrategia: lookup-first com escape pra raciocinio livre se nenhum
    template casar.

    Flag E4 TEMPLATES_POLETTO_ENABLED (default ON): set false pra reverter
    v2.3 em A/B test sem code change.
    """
    if not _flag_enabled("TEMPLATES_POLETTO_ENABLED"):
        return ""
    return """=== TEMPLATE-FIRST POLETTO (PASSO 1 — TENTAR ANTES DE RACIOCINIO LIVRE) ===

REGRA DE OURO: o time Poletto classifica risco por TEMPLATES estruturais
2-D (fase processual + direcao do resultado). Antes de raciocinar livre
sobre detalhes, tente classificar este merito em UM dos 9 templates abaixo.
Se MATCH claro -> use o risco do template e cite o ID na justificativa.
Se NENHUM match -> caia no raciocinio livre (PROTOCOLO RISCO BASE Default
Baixo + sinais explicitos pra subir).

────────────────────────────────────────────────────────────────────────
T-B1 [BAIXO] — Apolice em fase pre-decisao 1g (apresentada/aceita SEM
sentenca de merito ainda):
  - Execucao Fiscal com Embargos a Execucao SEM decisao de 1a instancia
    (Embargos opostos, prazo em curso, ou tramitando sem julgamento)
  - Acao Anulatoria/Mandado de Seguranca SEM sentenca
  - Cumprimento (Definitivo ou Provisorio) de Sentenca para apresentacao
    de embargos a execucao SEM decisao 1g
  - Execucao de Titulo Extrajudicial SEM decisao 1g sobre embargos
  - Acao Civil Publica SEM sentenca
  - EF com prazo em curso pra opor Embargos (Embargos ainda nao distribuidos)

T-B2 [BAIXO] — Apolice + DECISAO FAVORAVEL ao Tomador (mesmo SEM transito):
  - EF com Embargos julgados TOTALMENTE procedentes (sentenca ou acordao)
  - Anulatoria/MS com sentenca/acordao FAVORAVEL ao Tomador
  - EF SUSPENSA aguardando Anulatoria/MS com resultado FAVORAVEL ao Tomador
  - Anulatoria/MS com resultado favoravel ainda nao transitado
  - Cumprimento de Sentenca com sentenca favoravel ao Tomador
  - Sentenca parcialmente procedente ao Tomador determinando suspensao

T-B3 [BAIXO] — Estado pre-aceitacao da apolice:
  - "Aguarda-se a aceitacao da apolice" (estado inicial)
  - "Aguarda-se a decisao sobre a aceitacao da apolice"
  - Tutela cautelar extinta porque EF foi ajuizada (transicao tutela -> EF
    eh fluxo normal, nao desfavoravel)

T-B4 [BAIXO] — Caso resolvido por outra via:
  - EF EXTINTA por pagamento, parcelamento, ou anulacao do debito
  - Tomador informou pagamento integral, aguardando extincao
  - Adimplido o parcelamento, aguarda manifestacao do exequente
  - Tomador em Recuperacao Judicial com autos SUSPENSOS por isso
  - Nao localizada apolice da Seguradora no processo (sem risco de
    acionamento mesmo havendo decisao adversa, porque nao ha apolice viva)

────────────────────────────────────────────────────────────────────────
T-M1 [MEDIO] — Sentenca DESFAVORAVEL ao Tomador em 1g + recurso/prazo
pendente (NAO chegou em 2g ainda):
  - EF com Embargos julgados improcedentes (ou parcialmente) + prazo em
    curso pra recorrer da sentenca
  - EF com Embargos improcedentes + apelacao PENDENTE de julgamento
  - Anulatoria/MS com sentenca desfavoravel + apelacao pendente
  - EF SUSPENSA aguardando Anulatoria/MS com sentenca desfavoravel + apelacao
  - Cumprimento de Sentenca com embargos a execucao improcedentes +
    recursos pendentes

T-M2 [MEDIO] — Acordo de parcelamento Tomador <-> Segurado em curso:
  - Execucao suspensa aguardando cumprimento de acordo
  - Exigibilidade suspensa por parcelamento em cumprimento

────────────────────────────────────────────────────────────────────────
T-A1 [ALTO] — 2a INSTANCIA confirmou decisao DESFAVORAVEL ao Tomador,
SEM transito em julgado ainda:
  - EF com Embargos improcedentes + 2a instancia confirmou (sem transito)
  - EF SUSPENSA aguardando Anulatoria/MS com sentenca desfavoravel
    MANTIDA em 2g (sem transito)
  - Cumprimento de Sentenca com acordao desfavoravel nos embargos +
    recursos pendentes (REsp/RE)
  - Apolice em Cumprimento Provisorio com acordao desfavoravel nos embargos

T-A2 [ALTO] — TRANSITO EM JULGADO desfavoravel ao Tomador, SEM intimacao
formal da Seguradora ainda:
  - EF com Embargos improcedentes + transito em julgado desfavoravel
    (Tomador ainda NAO intimado pra pagamento)
  - Anulatoria/MS com sentenca desfavoravel transitada
  - Cumprimento de Sentenca com acordao desfavoravel transitado

────────────────────────────────────────────────────────────────────────
T-AA1 [ALTISSIMO] — Transito desfavoravel + Exequente PETICIONOU intimando
a Seguradora pra pagar (e/ou ja intimou):
  - EF + Embargos improcedentes + 2g desfavoravel transitada + Peticao
    do Exequente requerendo INTIMACAO DA SEGURADORA pra pagamento
  - Tomador intimado pra pagamento, sem manifestacao

────────────────────────────────────────────────────────────────────────
ESCAPE — quando IGNORAR o template:
  - Penhora online EFETIVADA com valor bloqueado documentado (BACENJUD
    positivo, "valor sequestrado" explicito) num caso classificado T-B*:
    suba pra Alto.
  - Recurso com efeito SUSPENSIVO atribuido em caso T-A2: desca pra Medio
    (a constricao esta sustada).
  - Tomador-autor em Tutela Cautelar com extincao sem merito ISOLADA (sem
    EF subsequente): trate como T-B3 (aguarda aceitacao).

OUTPUT: na justificativa, cite o template (ex: "Classificacao Poletto T-B1:
apolice apresentada em Anulatoria sem sentenca de 1g"). Se nenhum template
casar, escreva "[sem match com template Poletto]" e prossiga com
raciocinio livre."""


def _build_bloqueio_prob_exito() -> str:
    """REGRA v2.4: bloqueia `probabilidade_exito` da L2 como sinal de risco.

    Cards L3 v2.3 mostraram L3 citando "prob_exito=remota / score 0.0001"
    pra subir risco pra Alto em casos que Poletto classificou Baixo
    (m=90 ENERGISA, m=122 ATACADAO). Esse sinal vem da L2 que computa
    com base na MATRIZ DAYCOVAL (corretora atual, conservadora por design).

    Poletto eh corretora NOVA, com criterio diferente. Usar prob_exito
    Daycoval como input ao classificar vs Poletto = viesar TODA classificacao
    pra ser-mais-Daycoval. Bloquear esse sinal recupera autonomia do L3 pra
    seguir templates + regras processuais explicitas.

    Pluggada ANTES de _build_templates_poletto (ordem importa — sinal
    bloqueado precisa estar fora antes do lookup).

    Flag E5 BLOQUEIO_PROB_EXITO_ENABLED (default ON): set false pra reverter
    v2.4 em A/B test sem code change.
    """
    if not _flag_enabled("BLOQUEIO_PROB_EXITO_ENABLED"):
        return ""
    return """=== BLOQUEIO DE SINAL Daycoval-residual (CRITICA — v2.4) ===

A L2 pode te entregar campos como `probabilidade_exito` (com valores tipo
'remota', 'possivel', 'provavel', 'pacifica') ou `score` numerico de 0 a 1.
Esses campos vem da MATRIZ DAYCOVAL — a corretora ATUAL (em substituicao),
historicamente conservadora.

REGRA DURA: IGNORE COMPLETAMENTE `probabilidade_exito` e qualquer `score`
agregado da L2 ao decidir risco. Sao INPUTS CONTEXTUAIS de outro avaliador,
NAO evidencia processual.

Razao: o gold padrao deste sistema eh a corretora NOVA (Poletto). Usar
Daycoval-derived signals = enviesar a classificacao pra ser-mais-Daycoval,
contrariando o objetivo.

VOCE CLASSIFICA RISCO USANDO APENAS:
1. FASE PROCESSUAL (sem sentenca / sentenca 1g / 2g / transito / intimacao
   seguradora) — eixo dominante (templates T-B* / T-M* / T-A* / T-AA*)
2. DIRECAO DE DECISAO de MERITO explicita nos cards de mov
   (sentenca_favoravel_tomador, sentenca_desfavoravel_tomador, acordao_*)
3. SINAIS PROCESSUAIS EFETIVOS documentados (penhora online com
   `valor_bloqueado`, intimacao formal da seguradora, etc)

Se a justificativa que voce escreveria contem a expressao "probabilidade
de exito remota" / "score X" / "tese desfavoravel pela jurisprudencia" /
"matriz Daycoval" como motivo de subida — RESCRAVA sem esse motivo. Se
sem ele a subida nao se justifica por (1)+(2)+(3) acima, classifique como
o template ou raciocinio livre indicariam (default Baixo)."""


_REGRA_PARADIGMA_OVERRIDE_PRE_TRANSITO = """

REGRA — PARADIGMA POLETTO COMO OVERRIDE EM FASE PRE-TRANSITO:

Cards do L2 podem trazer 1+ paradigmas Poletto indicando "Alto" pra tese
canonica (paradigma.sentido='desfavoravel' ao Tomador). Esses paradigmas
sao jurisprudencia consolidada da TESE em instancias superiores
(STF/STJ/TJs majoritarios), nao do CASO individual atual.

REGRA DURA DE OVERRIDE: Quando TODAS as condicoes abaixo aplicam:
  (i)   ha >=1 paradigma carregado E >=50% dos paradigmas indicam Alto
        (sentido='desfavoravel'), E
  (ii)  decisao_vigente.sentido='favoravel' ao Tomador EM 1g (sem
        transito em julgado certificado), E
  (iii) ha recurso pendente OU prazo recursal em curso, E
  (iv)  tese_canonica NAO eh pro_contribuinte_firmado (Tema STF/STJ ou
        Sumula que mata definitivamente a tese contraria)

ENTAO: ELEVE classificacao UM nivel ACIMA do template que matchou:
  - Template Baixo (T-B1/T-B2/T-B3) -> MEDIO
  - Template Medio (T-M1/T-M2) -> ALTO
  - Template Alto+ (T-A*/T-AA*) -> mantem (ja eh alto)

Cite na justificativa: (a) o template originalmente matchado, (b) o(s)
paradigma(s) que dispararam o override, (c) por que o override aplica
(decisao 1g favoravel + paradigma jurisprudencial superior contraria
indicam risco prospectivo de reversao).

Exemplo m=680006 BANCO MERCANTIL IRPJ Stock Options:
- 1g procedente (sentido='favoravel', T-B2 indicaria Baixo)
- 1 paradigma Poletto Alto em Stock Options (STJ majoritario contra)
- Sem transito em julgado, agravo de instrumento pendente
- Tese NAO eh pro_contribuinte_firmado
- OVERRIDE: classifique MEDIO (nao Baixo via T-B2, nao Alto direto)
- Justificativa: "T-B2 matchou por sentenca 1g favoravel, mas paradigma
  Poletto consolidado pra Stock Options aponta reversao provavel em
  STJ -> risco MEDIO ate transito (subida 1 nivel)."

Scope: aplica APENAS a meritos com >=1 paradigma desfavoravel. Meritos
SEM paradigma permanecem governados pelo template default (nenhum
override). Paradigmas que apontam Baixo (sentido='favoravel') NAO
disparam override (paradigma favoravel reforca template Baixo)."""


def _build_regras_anti_falso_alto() -> str:
    """REGRAS DURAS contra falsos-positivos de subida de risco.

    Adicionado 2026-05-25 apos mass cascade re-run regredir 62.4% -> 57.1%.
    Diagnostico: 4 padroes principais empurrando risco pra cima sem motivo
    real. Esta funcao cobre 2 dos 4 (extincao sem merito + termo de penhora).

    Pluggada APOS _build_protocolo_postura_default + ANTES de _build_rules.
    Aplica a TODOS os tipos (fiscal/trab/civel/misto).

    2026-05-29: adicionada REGRA paradigma_override_pre_transito (flag E8
    PARADIGMA_OVERRIDE_PRE_TRANSITO_ENABLED, default ON). Cobre underpenalty
    Alto->Baixo identificado na revalidacao 2026-05-29 (m=680006 BANCO
    MERCANTIL IRPJ Stock Options sample). Memory:
    revalidation-2026-05-29-gemini-burst-bottleneck.
    """
    base = """=== REGRAS DURAS ANTI FALSO-POSITIVO (CRITICA) ===

REGRA — EXTINCAO SEM MERITO eh PROCESSUAL, NAO move risco isoladamente:

L1/L2 podem mandar decisao_vigente com natureza='extinto_sem_merito' E
sentido='desfavoravel' quando o Tomador eh AUTOR (Tutela Cautelar,
Anulatoria, MS, Embargos, Excecao Pre-Executividade, Rescisoria). Esse
sinal eh CORRETO em nivel de carta (Tomador queria algo, processo
extinto sem julgar merito = derrota processual).

MAS pro RISCO DE ACIONAMENTO DA APOLICE no MERITO, extincao sem merito
NAO move risco isoladamente. Razao: extincao sem merito NAO julga o
conteudo da causa — eh processual. NAO consolida divida nem dispara
acionamento da apolice por si so.

REGRA DURA: quando o unico sinal "desfavoravel" no merito eh extincao
sem merito (mesmo transitada), classifique risco como BAIXO. Considere
risco superior APENAS se houver OUTROS sinais explicitos de merito
desfavoravel:
- Execucao Fiscal subsequente com penhora online EFETIVADA, OR
- Acordao 2g de merito desfavoravel em processo conexo do mesmo merito, OR
- Intimacao da seguradora pra pagamento ja deferida, OR
- Transito em julgado de decisao DE MERITO desfavoravel (nao da extincao)

Trate decisao_vigente.sentido='desfavoravel' + natureza='extinto_sem_merito'
como sinal NEUTRO pra fins de classificacao do MERITO (mesmo que L2 marcou
desfavoravel corretamente do ponto de vista da carta).

REGRA — TERMO DE PENHORA != PENHORA EFETIVADA:

"Termo de Penhora" no DJe pode ser:
(a) Termo PROTOCOLAR/CARTORIAL — apenas registro de juntada de termo,
    sem constricao efetiva. Comum em fases iniciais da execucao.
(b) Termo de PENHORA EFETIVADA — constricao real, com bens/valores
    bloqueados/sequestrados. Esse SIM eh gatilho de risco.

Pra distinguir, busque na descricao da mov + docs anexados sinais de
EFETIVACAO:
- "valor bloqueado", "valor sequestrado", "transferencia pra conta judicial"
- "indisponibilidade efetivada", "BACENJUD positivo", "SISBAJUD positivo"
- "auto de penhora" com bem especifico descrito
- "constricao judicial deferida E cumprida"

Quando a mov diz APENAS "Juntada de Termo de Penhora" ou similar sem
sinal de efetivacao, NAO trate como [ALTISSIMO] penhora online deferida.
Trate como sinal protocolar = NAO move risco isoladamente.

REGRA DURA: bullet "[ALTISSIMO] penhora online deferida" no escala
fiscal/civel/trab exige EVIDENCIA EXPLICITA de efetivacao (valor
bloqueado documentado, BACENJUD positivo, etc). Sem evidencia
explicita, default Baixo."""
    if _flag_enabled("PARADIGMA_OVERRIDE_PRE_TRANSITO_ENABLED"):
        base += _REGRA_PARADIGMA_OVERRIDE_PRE_TRANSITO
    return base


def _build_justifique_subida() -> str:
    """REGRA DURA — JUSTIFIQUE A SUBIDA. Comum a todos os tipos."""
    return """REGRA DURA — JUSTIFIQUE A SUBIDA:
Pra atribuir Medio/Alto/Altissimo, a justificativa DEVE citar
explicitamente:
1. QUAL processo carrega o sinal explicito (CNJ)
2. QUAL evento concreto (data + tipo: sentenca/transito/intimacao/penhora)
3. POR QUE encaixa no nivel escolhido (referencia ao bullet da escala)
4. CONFIRMAR que NAO eh decisao processual (vide regra acima)

Sem esses 4 itens citados na narrativa, a classificacao DEVE ser Baixo.
"Risco intermediario por sinais ambiguos" NAO eh argumento valido — eh
sinal de Baixo (sem evidencia explicita) OU classificacao indevida."""


def _build_field_instructions() -> str:
    """=== INSTRUCOES POR CAMPO === — 11 itens sobre formato JSON output.

    Comum a todos os tipos: schema de output e o mesmo independente do
    tipo_judicial dominante. Soh os exemplos textuais sao genericos
    suficientes pra cobrir fiscal/trab/civel."""
    return """=== INSTRUCOES POR CAMPO ===

1. risco (UM dos 4 niveis): aplique o PROTOCOLO DE RISCO BASE acima.
   Default = Baixo. So sobe com sinal explicito (decisao desfavoravel
   transitada, intimacao seguradora, penhora, cumprimento de sentenca
   determinado, tese contraria firmada, etc — vide escala completa).

2. justificativa: 2-4 paragrafos PT-BR.
   - Paragrafo 1: estado factual (qual processo carrega a decisao mais decisiva, sentido)
   - Paragrafo 2: aspectos suportivos (apolice aceita? CDAs/AIIMs? tomador com risco?)
   - Paragrafo 3: justificativa do nivel escolhido vs nivel adjacente
   - Cite ID/CNJ dos processos relevantes.

3. narrativa_executiva: 1 frase pro time comercial. Estilo: "Mérito em fase de execucao
   com 3 CDAs ICMS estaduais (~R$ 5M), apólice aceita, sentenca de 1g desfavoravel
   pendente apelacao. Médio."

4. decisao_atual: a decisao mais recente que governa o MERITO HOJE (do processo principal
   OU do conexo se principal nao tem decisao). Inclua processo_de_origem.

5. ciclo_garantia: timeline cross-processo unificada (todos os eventos de garantia de
   todos os processos do merito), ordenada por data ASC.

6. valor_em_disputa_melhor_evidencia: maior valor entre os processos (BRL).
   valor_garantia_melhor_evidencia: SOMA dos valor_garantia das apolices aceitas (BRL).

7. peca_pivo_merito: a UNICA mov mais decisiva do merito inteiro (pode estar em qualquer
   processo). Use processo_numero + mov_id do peca_pivo_candidata da camada 2 mais
   load-bearing. NAO INVENTE: se nenhum processo tem peca-pivo clara, deixe motivo="".

8. proximos_passos_provaveis: lista de 2-4 acoes esperadas pro merito como um todo.

9. probabilidade_exito_merito (Matriz Daycoval agregada — INPUT FORTE PRO RISCO):
   Cada processo_synthesis ja traz `probabilidade_exito` com score (1.0/0.7/0.4/0.0001)
   da Matriz Daycoval. Voce agrega no nivel do MERITO:

   a) classificacao_agregada + score_agregado:
      - V1 (default): MEDIA PONDERADA POR valor_em_disputa dos processos.
        Conexos contam metade do peso (multiplicar valor_em_disputa do conexo por 0.5
        antes do calculo). Se valor_em_disputa estiver null em algum, use peso=1.
        Mapeie de volta pro bucket: score >= 0.85 -> "provavel", >= 0.55 -> "possivel",
        >= 0.20 -> "poucas_chances", < 0.20 -> "remota".
      - Se UM SO processo (sem conexos), score_agregado = score do processo principal.
   b) breakdown_por_processo: lista com {processo_numero, role, classificacao, score,
      peso_aplicado, valor_em_disputa} pra audit.
   c) metodo_agregacao: "media_ponderada_valor_disputa" (V1 default).
   d) contribuicao_no_risco: 1 frase explicando COMO essa prob_exito agregada
      influenciou o risco final que voce escolheu (vide regra F abaixo).

10. confidence (0-1):
    - 0.9+ quando decisao_atual clara em todos os processos
    - 0.7-0.8 quando ambigua mas com sinal majoritario
    - 0.5-0.7 quando muitos processos sem decisao
    - < 0.5 quando dados muito esparsos

11. evidence_artifacts: 3-7 itens citando OS PROCESSOS/CARDS mais decisivos.
    kind = processo_synthesis | mov_factsheet | apolice | conexo | cda | aiim | tomador | merito
    ref = processo_numero, mov_id, cda_number, cnpj_basico, etc."""


def _build_lembrete_final(req: MeritoSynthesisRequest) -> str:
    """Recency anchor no fim do prompt — combate Lost-in-the-Middle.

    v2.1: substitui _build_output_schema legacy (FORMATO DE SAIDA duplicava
    o que response_schema=MeritoSynthesisCard ja enforça nativamente).
    Reforça as 3 regras criticas que devem governar a decisao final.
    """
    return f"""<lembrete_final>
Antes de emitir risco final, confirme:
1. Polos identificados? Tomador eh quem? (releia GLOSSARIO ROLES no topo).
2. Consistency check OK? Argumentos pro-Alto exigem risco=Alto/Altissimo
   (releia CONSISTENCY CHECK no topo).
3. Default = Baixo. Subida requer sinal explicito citando CNJ + evento
   concreto + bullet da escala (REGRA JUSTIFIQUE A SUBIDA).

Output: JSON estruturado conforme schema MeritoSynthesisCard (enforced via
response_schema do Gemini). merito_id={req.merito_id}, merito_context=
'{req.merito_context}' devem ser echo do input.
</lembrete_final>"""


# ─── Variant: ESCALA bullets (per tipo_judicial) ───────────────────────────


def _build_escala_fiscal() -> str:
    """ESCALA bullets pra merito FISCAL-dominante.

    Linguagem: Execucao Fiscal, intimacao seguradora, penhora online,
    aceite de apolice, tese pro_fazenda_firmado."""
    return """ESCALA EXPLICITA (em ordem crescente de severidade — primeiro nivel
que CASE, escolha; senao continue Baixo):

[ALTISSIMO] gatilho de acionamento JA disparado:
- transito em julgado CERTIFICADO desfavoravel + execucao fiscal ativa
- cumprimento de sentenca contra Tomador ja determinado
- intimacao da seguradora pra pagamento ja deferida
- penhora online deferida cobrindo o debito
- Tomador em RJ com plano em risco AND decisao desfavoravel transitada
  em conexa

[ALTO] gatilho iminente / sem rota de escape clara:
- decisao 2g desfavoravel SEM REsp/RE viavel (mantida em STJ ou STF)
- intimacao pra pagamento solicitada pela Fazenda (ainda nao deferida
  mas em curso)
- 1g desfavoravel + tese pro_fazenda_firmado (Regra G) sem contrapeso
- Tomador em RJ com plano em risco AND processo principal com decisao
  desfavoravel pendente
- apolice RECUSADA pelo juizo OR levantada por substituicao desfavoravel

[MEDIO] degradacao prospectiva concreta mas reversao razoavel:
- decisao 1g desfavoravel + apelacao pendente (efeito suspensivo CPC
  art. 1.012) SEM tese pro_fazenda_firmado
- decisao parcialmente desfavoravel + recurso pendente
- 1g favoravel + acordao 2g desfavoravel + REsp/RE admissivel pendente

[BAIXO] (default) — qualquer cenario sem sinal explicito acima:
- nenhuma decisao desfavoravel transitada
- apolice apresentada (mesmo sem aceitacao explicita registrada)
- processo em fase inicial / instrucao / aguardando manifestacao
- 1g favoravel ao Tomador (com ou sem recurso da contraparte) SEM tese
  pro_fazenda_firmado contraria
- processo extinto sem merito (regra H.1)
- execucao fiscal suspensa por causa externa favoravel (regra H)
- tese pro_contribuinte_firmado em vigor (regra G.1)"""


def _build_escala_trabalhista() -> str:
    """ESCALA bullets pra merito TRABALHISTA-dominante.

    Linguagem: Reclamacao Trabalhista, cumprimento provisorio/definitivo,
    levantamento de deposito recursal, RR, AIRR, Sumula TST."""
    return """ESCALA EXPLICITA (em ordem crescente de severidade — primeiro nivel
que CASE, escolha; senao continue Baixo):

[ALTISSIMO] gatilho de acionamento JA disparado:
- transito em julgado CERTIFICADO de sentenca trabalhista desfavoravel
  + cumprimento definitivo iniciado contra Tomador
- levantamento de deposito recursal autorizado pra beneficiario
- penhora online deferida cobrindo o valor da obrigacao
- intimacao da seguradora pra pagamento ja deferida
- Tomador em RJ com plano em risco AND condenacao trabalhista transitada
  em processo conexo (responsabilidade subsidiaria, sucessao trabalhista)

[ALTO] gatilho iminente / sem rota de escape clara:
- acordao TRT 2g desfavoravel SEM RR (Recurso de Revista) viavel OU
  com juizo de admissibilidade do RR ja negado
- cumprimento PROVISORIO determinado contra Tomador (CLT art. 899
  c/c CPC art. 520)
- 1g desfavoravel + Sumula TST consolidada contraria sem distinguishing
  (ex: Sumula 331 TST em terceirizacao tipica) — vide Regra G
- Tomador em RJ com plano em risco AND processo principal com decisao
  desfavoravel pendente
- apolice RECUSADA pelo juizo OR levantada por substituicao desfavoravel
- penhora sobre faturamento da empresa Tomadora determinada

[MEDIO] degradacao prospectiva concreta mas reversao razoavel:
- decisao 1g desfavoravel + recurso ordinario pro TRT pendente SEM
  Sumula/OJ TST consolidada contraria
- decisao parcialmente desfavoravel (procedente em parte) + recurso pendente
- 1g favoravel + acordao TRT 2g desfavoravel + RR admissivel pendente
- Sumula TST oscilante sobre a tese OU OJ SDI-1 sem unanimidade

[BAIXO] (default) — qualquer cenario sem sinal explicito acima:
- nenhuma decisao desfavoravel transitada
- apolice apresentada (mesmo sem aceitacao explicita registrada)
- deposito recursal feito como garantia (mitigante de liquidez)
- processo em fase de instrucao / audiencia / aguardando manifestacao
- 1g favoravel ao Tomador SEM Sumula TST contraria firmada
- processo arquivado / extinto sem julgamento de merito (CLT art. 765,
  CPC art. 485)
- execucao trabalhista suspensa aguardando decisao em conexo favoravel
- Sumula TST consolidada favoravel ao Tomador OU Tema STF favoravel
  ao empregador firmado (regra G.1)"""


def _build_escala_civel() -> str:
    """ESCALA bullets pra merito CIVEL-dominante.

    Linguagem: Acao Indenizatoria/Cobranca, cumprimento de sentenca,
    REsp/RE, AREsp, Tema repetitivo STJ, Sumula STJ."""
    return """ESCALA EXPLICITA (em ordem crescente de severidade — primeiro nivel
que CASE, escolha; senao continue Baixo):

[ALTISSIMO] gatilho de acionamento JA disparado:
- transito em julgado CERTIFICADO desfavoravel + cumprimento de
  sentenca em curso (CPC art. 523+)
- satisfacao via levantamento autorizada pela autoridade competente
- penhora online deferida cobrindo o credito do exequente
- intimacao da seguradora pra pagamento ja deferida
- Tomador em RJ com plano em risco AND decisao civel desfavoravel
  transitada em conexa

[ALTO] gatilho iminente / sem rota de escape clara:
- acordao TJ 2g desfavoravel SEM REsp/RE viavel OU com juizo de
  admissibilidade do REsp ja negado (AREsp improvido)
- 1g desfavoravel + Tema repetitivo STJ ou Sumula STJ contraria sem
  distinguishing claro (vide Regra G)
- cumprimento provisorio determinado contra Tomador
- Tomador em RJ com plano em risco AND processo principal com decisao
  desfavoravel pendente
- apolice RECUSADA pelo juizo OR levantada por substituicao desfavoravel

[MEDIO] degradacao prospectiva concreta mas reversao razoavel:
- sentenca 1g desfavoravel + apelacao pendente (efeito suspensivo CPC
  art. 1.012) SEM Tema repetitivo STJ contrario firmado
- decisao parcialmente desfavoravel + recurso pendente
- 1g favoravel + acordao 2g desfavoravel + REsp/RE admissivel pendente
  (admissibilidade ainda nao apreciada)
- Tema STJ pendente de julgamento envolvendo a tese da causa

[BAIXO] (default) — qualquer cenario sem sinal explicito acima:
- nenhuma decisao desfavoravel transitada
- apolice apresentada (mesmo sem aceitacao explicita registrada)
- processo em fase de instrucao / audiencia / aguardando manifestacao
- 1g favoravel ao Tomador (com ou sem recurso da contraparte) SEM
  Tema STJ ou Sumula STJ contraria firmada
- processo extinto sem merito (regra H.1)
- execucao suspensa por causa externa favoravel (regra H)
- Tema repetitivo STJ ou Sumula STJ favoravel ao Tomador em vigor
  (regra G.1)"""


def _build_escala_misto() -> str:
    """ESCALA bullets pra merito MISTO (>=2 tipos ou dominancia <80%).

    Linguagem ABSTRATA: 'qualquer processo do merito', 'sinal
    desfavoravel transitado' — sem se comprometer com vocabulario
    fiscal/trab/civel especifico."""
    return """ESCALA EXPLICITA (mérito MISTO — abstrata, aplicavel a qualquer tipo):

NOTA: este mérito mistura tipos judiciais distintos (>=2 tipos OU dominancia
<80%). Use bullets ABSTRATOS abaixo e aplique regras CONDICIONAIS por
processo: pra processo fiscal use vocabulario fiscal (EF, tese STF), pra
trabalhista use TST/RR, pra civel use STJ/REsp. CITE explicitamente o
tipo do processo que carrega o sinal na narrativa.

[ALTISSIMO] gatilho de acionamento JA disparado em QUALQUER processo do mérito:
- transito em julgado CERTIFICADO desfavoravel + execucao/cumprimento ativo
- intimacao da seguradora pra pagamento ja deferida em qualquer processo
- penhora online deferida cobrindo o debito
- Tomador em RJ com plano em risco AND decisao desfavoravel transitada

[ALTO] gatilho iminente / sem rota de escape clara em QUALQUER processo:
- decisao 2g desfavoravel SEM recurso superior viavel
- 1g desfavoravel + tese contraria firmada (Sumula vinculante / Tema
  repetitivo / Sumula TST consolidada) sem contrapeso
- cumprimento provisorio determinado contra Tomador
- apolice RECUSADA pelo juizo OR levantada por substituicao desfavoravel

[MEDIO] degradacao prospectiva concreta mas reversao razoavel:
- decisao 1g desfavoravel + recurso pendente SEM tese contraria firmada
- decisao parcialmente desfavoravel + recurso pendente

[BAIXO] (default) — sem sinal explicito acima:
- nenhuma decisao desfavoravel transitada em nenhum processo
- apolice apresentada (mesmo sem aceitacao explicita)
- processos em fase inicial / instrucao
- 1g favoravel ao Tomador SEM tese contraria firmada
- processos extintos sem merito
- execucoes suspensas por causa externa favoravel"""


# ─── Variant: DECISAO PROCESSUAL events (per tipo_judicial) ────────────────


_DECISAO_PROCESSUAL_INTRO = """REGRA DURA — DECISAO PROCESSUAL NAO MOVE RISCO:

Eventos PROCESSUAIS NAO equivalem a decisao desfavoravel de merito,
mesmo se transitados em julgado. NAO sobem risco — quando vier do L2
como decisao_vigente.sentido='desfavoravel', RECLASSIFIQUE pra neutro
porque o L2 confundiu processual com merito."""


_DECISAO_PROCESSUAL_TESTE = """SO movem risco (sobem pra Medio/Alto/Altissimo) decisoes DE MERITO
sobre o CONTEUDO da causa:
- Sentenca de procedencia/improcedencia em 1g
- Acordao de provimento/desprovimento do recurso de apelacao em 2g
- Acordao do STJ/STF/TST que reforma OU mantem o merito ja julgado
- Transito em julgado da decisao de merito (nao de processual)

TESTE PRA DUVIDA: olhe o que a decisao DECIDIU.
- Decidiu sobre o credito/obrigacao/relacao juridica material? -> MERITO
- Decidiu sobre como o processo deve tramitar (recurso cabe, defesa
  cabe, prazo, suspensao)? -> PROCESSUAL = nao move risco.

Quando em duvida (decisao ambigua), NAO suba — fique em Baixo.
False negative (deixar Baixo erradamente) eh menos danoso que false
positive (atribuir Alto pra mov processual + cliente recebe alerta
indevido)."""


def _build_decisao_processual_fiscal() -> str:
    """Lista de eventos processuais que NAO movem risco — FISCAL."""
    return f"""{_DECISAO_PROCESSUAL_INTRO}

Lista NAO-EXAUSTIVA de eventos processuais FISCAIS (NAO movem risco):
- Agravo de instrumento (provido OU desprovido) — recurso sobre decisao
  interlocutoria; NAO julga merito da causa.
- Excecao de pre-executividade (acolhida OU rejeitada) — defesa
  preliminar sobre admissibilidade da execucao fiscal; NAO decide o
  credito tributario.
- Embargos de declaracao (acolhidos OU rejeitados) — esclarecimento de
  decisao anterior; NAO eh novo julgamento de merito.
- Juizo de admissibilidade de REsp/RE/Agravo Interno em REsp (positivo
  OU negativo) — porta de entrada do recurso superior; NAO decide
  merito. "STJ negou seguimento ao REsp" eh processual, nao desfavoravel
  de merito.
- Revogacao de efeito suspensivo de recurso — processual sobre
  tramitacao; abre porta pra Fazenda agir mas NAO consolida divida.
- Arquivamento provisorio da execucao fiscal, suspensao processual,
  baixa administrativa, prescricao intercorrente (CTN art. 174) — atos
  de tramitacao OU encerramento sem julgamento de merito.

{_DECISAO_PROCESSUAL_TESTE}"""


def _build_decisao_processual_trabalhista() -> str:
    """Lista de eventos processuais que NAO movem risco — TRABALHISTA."""
    return f"""{_DECISAO_PROCESSUAL_INTRO}

Lista NAO-EXAUSTIVA de eventos processuais TRABALHISTAS (NAO movem risco):
- Agravo de instrumento em RR (AIRR — Agravo de Instrumento em Recurso
  de Revista, provido OU desprovido) — recurso sobre admissibilidade do
  RR; NAO julga merito.
- Agravo regimental em RR (AgR-RR) — recurso interno sobre decisao
  monocratica do TST; processual.
- Agravo regimental / Agravo Interno em qualquer instancia trabalhista
  — recurso sobre tramitacao do recurso principal.
- Embargos infringentes em TST (Lei 13.467/2017 reduziu cabimento, mas
  ainda possivel) — recurso sobre divergencia jurisprudencial entre
  Subsecoes; NAO julga merito da causa originaria.
- Embargos de declaracao (acolhidos OU rejeitados) — esclarecimento de
  decisao anterior; NAO eh novo julgamento de merito.
- Juizo de admissibilidade de RR/Recurso Ordinario (positivo OU
  negativo) — "TST negou seguimento ao RR" eh processual, nao
  desfavoravel de merito.
- Revogacao de efeito suspensivo de recurso ordinario — processual
  sobre tramitacao; abre porta pro cumprimento provisorio mas NAO
  consolida condenacao.
- Arquivamento por abandono (CLT art. 844), arquivamento por ausencia
  do reclamante, extincao por carencia da acao — atos de tramitacao OU
  encerramento sem julgamento de merito.

{_DECISAO_PROCESSUAL_TESTE}"""


def _build_decisao_processual_civel() -> str:
    """Lista de eventos processuais que NAO movem risco — CIVEL."""
    return f"""{_DECISAO_PROCESSUAL_INTRO}

Lista NAO-EXAUSTIVA de eventos processuais CIVEIS (NAO movem risco):
- Agravo de instrumento (provido OU desprovido) — recurso sobre decisao
  interlocutoria; NAO julga merito da causa principal.
- Agravo interno em decisao monocratica de relator (TJ, STJ, STF) —
  processual sobre tramitacao recursal; NAO decide o conflito material.
- Embargos de declaracao (acolhidos OU rejeitados) — esclarecimento de
  decisao anterior; NAO eh novo julgamento de merito.
- Agravo em Recurso Especial / Extraordinario (AREsp/ARE), provido OU
  desprovido — recurso sobre admissibilidade do REsp/RE; NAO decide
  merito. "STJ negou seguimento ao REsp" / "STF nao conheceu RE" eh
  processual, nao desfavoravel de merito.
- Juizo de admissibilidade de REsp/RE em segundo grau (positivo OU
  negativo) — porta de entrada do recurso superior; NAO decide merito.
- Embargos a Execucao (rejeitados) sobre questao processual (nulidade
  da CDA, prescricao processual, ilegitimidade) — NAO decide o credito
  material.
- Impugnacao ao cumprimento de sentenca (rejeitada) sobre questao
  processual (CPC art. 525) — defesa sobre tramitacao do cumprimento;
  NAO altera o titulo executivo.
- Suspensao processual, sobrestamento por tema afetado, prescricao
  intercorrente, extincao por desistencia OU abandono — atos de
  tramitacao OU encerramento sem julgamento de merito.

{_DECISAO_PROCESSUAL_TESTE}"""


def _build_decisao_processual_misto() -> str:
    """Lista de eventos processuais que NAO movem risco — MISTO (abstrato)."""
    return f"""{_DECISAO_PROCESSUAL_INTRO}

Lista NAO-EXAUSTIVA de eventos processuais (NAO movem risco em mérito misto):
- Recursos sobre admissibilidade ou tramitacao (agravo de instrumento,
  agravo interno, agravo regimental, agravo em REsp/RE, AIRR, AgR-RR)
  — processual, NAO julga merito.
- Embargos de declaracao (acolhidos OU rejeitados) — esclarecimento de
  decisao anterior; NAO eh novo julgamento de merito.
- Juizo de admissibilidade de recurso superior (REsp/RE/RR em qualquer
  instancia) — porta de entrada; NAO decide merito.
- Revogacao de efeito suspensivo — processual sobre tramitacao.
- Suspensao processual, arquivamento provisorio, prescricao
  intercorrente, extincao por carencia/abandono — atos de tramitacao
  OU encerramento sem julgamento de merito.
- Embargos a execucao OU impugnacao ao cumprimento sobre questao
  processual (nulidade, ilegitimidade, prescricao processual) — NAO
  decide credito material.

{_DECISAO_PROCESSUAL_TESTE}"""


# ─── Variant: REGRAS DE OURO A-H.1 (per tipo_judicial) ─────────────────────


_REGRAS_DE_OURO_HEADER = "=== REGRAS DE OURO ==="


_REGRAS_AD_COMUM = """A. NAO INVENTE. Se nenhum processo_synthesis tem decisao_vigente, decisao_atual.sentido=null.
B. Tomador em RJ NAO sobe risco automaticamente. RJ pode SUSPENDER o processo (Baixo).
   Mas se ha processo com decisao desfavoravel TRANSITADA + tomador em RJ -> Altissimo.
C. CDA/AIIM contam pra magnitude do valor em disputa MAS nao mudam o risco diretamente -
   sao contexto descritivo. Risco vem do ESTADO DOS PROCESSOS.
D. Peca-pivo do merito pode ser de CONEXO (nao do principal). Ex: anulatória conexa
   julgou improcedente -> isso e pivo mesmo se principal e Embargos sem sentenca."""


_REGRA_F_COMUM = """F. PROBABILIDADE DE EXITO (Daycoval) E INPUT FORTE PRO RISCO, NAO SUBSTITUI:
   - prob_exito agregada ALTA (>= 0.85, "provavel") -> EMPURRA risco pra BAIXO
     (mas nao supera trans em julgado desfavoravel — esse e Altissimo independente)
   - prob_exito BAIXA (< 0.20, "remota") -> EMPURRA risco pra ALTO
     (mesmo sem decisao desfavoravel ainda, pq a perda eventual e provavel)
   - prob_exito MEDIA (0.20-0.85) -> deixa o risco governado pelo estado atual
     (decisao_vigente, lifecycle_garantia, etc.)
   - A `contribuicao_no_risco` deve EXPLICAR essa influencia em 1 frase."""


_REGRA_H1_COMUM = """H.1 EXTINCAO SEM MERITO NAO CONSOLIDA DIVIDA:
   Decisao com natureza='extinto_sem_merito' (mesmo transitada) NAO julga
   o conteudo da causa — eh decisao processual. Tomador NEM ganhou NEM
   perdeu o merito. O processo extinto NAO move risco. Se houver Execucao
   subsequente, classificar pela situacao DELA, nao pela extincao.

   Cenario tipico: Anulatoria/Acao Declaratoria extinta sem merito por
   falta de pressuposto, tomador segue na Execucao. NAO classificar como
   Altissimo so por causa do "transito" da extincao — extincao sem merito
   eh neutra."""


def _build_regras_ouro_fiscal() -> str:
    """REGRAS DE OURO F/G/G.1/G.2/H/H.1 — FISCAL.

    Exemplos: Tema 372 STF (CSLL), Tema 1226 STJ (Stock Options), ICMS-ST,
    DIFAL, PIS-COFINS Tema 69 STF, Anulatoria/MS conexa."""
    return f"""{_REGRAS_DE_OURO_HEADER}

{_REGRAS_AD_COMUM}
{_REGRA_F_COMUM}

G. JURISPRUDENCIA (v2.2 DEPRECATED em L3, vive em L2):
   Antes L3 aplicava regras G/G.1/G.2 sobre `jurisprudencia` recebida no
   payload. v2.2: jurisprudencia migrada pra Camada 2 (regras J/J.1/J.2 do
   prompt L2 v2.2). risco_processo_intermediario de cada processo JA absorveu
   o sinal da juris. Confie nele.
   NAO tente re-aplicar regras de juris aqui — double-counting destroi
   coerencia entre L2 e L3.

H. REGRA DURA — PESO DA GARANTIA + SUSPENSAO POR CONEXO FAVORAVEL (FISCAL):
   Padrao identificado em ~30 meritos do Monit Poletto Mai/2026: cenarios
   onde a Execucao Fiscal esta SUSPENSA aguardando o tramite de uma
   Anulatoria/MS conexa com decisao FAVORAVEL ao Tomador (sentenca 1g
   procedente OU liminar em vigor), com apolice ja apresentada e aceita.
   Poletto classifica esses casos como Baixo. Engine v6 estava classificando
   como Medio/Alto por pesar excessivamente tese pro-Fazenda STF firmada
   (regra G) ignorando o contexto operacional.

   Quando o conjunto:
     (i)   apolice apresentada E aceita (lifecycle_garantia tem evento
           tipo='aceitacao' SEM levantamento posterior), AND
     (ii)  processo principal (Execucao Fiscal) SUSPENSO/sobrestado
           aguardando processo conexo (Anulatoria, MS, ADI, repercussao
           geral afetada), AND
     (iii) conexo tem decisao FAVORAVEL ao Tomador em vigor (mesmo 1g sem
           transito), OU processo principal extinto sem merito,
   ENTAO risco = "Baixo" — mesmo com tese pro_fazenda_firmado (regra G).

   Por que: o gatilho de acionamento da apolice e a Execucao Fiscal ATIVA
   exigir pagamento. Enquanto a execucao esta SUSPENSA por causa externa
   favoravel, NAO HA gatilho de curto prazo. A reversao eventual no STF
   pelo tema firmado eh prospectiva (3-5 anos) — nao move risco HOJE.
   Regra G prevalece sobre H apenas quando a SUSPENSAO sai (conexo perde
   o efeito suspensivo, retomada da execucao, intimacao da seguradora).

   Equivale a "diferimento operacional": apolice aceita protege liquidez +
   suspensao protege exigibilidade. Os dois juntos = risco baixo HOJE.

   CONTRAPESO LEGITIMO pra subir pra Medio mesmo com H aplicavel:
   - apolice vencida ou em renovacao com seguradora questionavel
   - tomador em RJ com plano em risco
   - sinal explicito de retomada iminente da execucao (despacho determinando
     intimacao da seguradora ja proferido)
   Sem contrapeso explicito = Baixo.

{_REGRA_H1_COMUM}"""


def _build_regras_ouro_trabalhista() -> str:
    """REGRAS DE OURO F/G/G.1/G.2/H/H.1 — TRABALHISTA.

    Exemplos: Tema 725 STF (Pejotizacao), Tema 1118 STF (Terceirizacao
    em saude), Sumula 331 TST (Terceirizacao), Sumula 363 TST (FGTS),
    OJ SDI-1 firmadas, Cumprimento Provisorio."""
    return f"""{_REGRAS_DE_OURO_HEADER}

{_REGRAS_AD_COMUM}
{_REGRA_F_COMUM}

G. JURISPRUDENCIA (v2.2 DEPRECATED em L3, vive em L2):
   Idem nota G da variant FISCAL. Sumulas TST / Temas STF trabalhistas agora
   pesam direto em risco_processo_intermediario via L2 prompt v2.2 (regras
   J/J.1/J.2). NAO re-aplicar aqui.

H. REGRA DURA — PESO DA GARANTIA + SUSPENSAO POR CONEXO FAVORAVEL (TRABALHISTA):
   Padrao analogo ao H fiscal mas adaptado pro contexto trabalhista:
   cenarios onde o Cumprimento Provisorio/Definitivo esta SUSPENSO aguardando
   tramite de processo conexo com decisao FAVORAVEL ao Tomador (ex: Acao
   Anulatoria de auto de infracao do Ministerio do Trabalho, MS contra
   determinacao de bloqueio, Acao de Reconhecimento de Inexistencia de
   Vinculo julgada procedente em 1g), com apolice ja apresentada e aceita.

   Deposito recursal feito (CLT art. 899, valor proporcional a alcada) e
   MITIGANTE adicional — garante liquidez do credor sem acionar apolice.

   Quando o conjunto:
     (i)   apolice apresentada E aceita (lifecycle_garantia tem evento
           tipo='aceitacao' SEM levantamento posterior), AND
     (ii)  processo principal (Cumprimento ou Reclamacao) SUSPENSO/sobrestado
           aguardando processo conexo, AND
     (iii) conexo tem decisao FAVORAVEL ao Tomador em vigor (mesmo 1g sem
           transito), OU processo principal extinto sem merito,
   ENTAO risco = "Baixo" — mesmo com Sumula TST contraria (regra G).

   Por que: o gatilho de acionamento da apolice e a EXIGENCIA ATIVA de
   pagamento. Enquanto o Cumprimento esta SUSPENSO por causa externa
   favoravel, NAO HA gatilho de curto prazo. A reversao eventual em
   instancia superior eh prospectiva — nao move risco HOJE.

   CONTRAPESO LEGITIMO pra subir pra Medio mesmo com H aplicavel:
   - apolice vencida ou em renovacao com seguradora questionavel
   - tomador em RJ com plano em risco
   - sinal explicito de retomada iminente do cumprimento (despacho
     determinando intimacao da seguradora ja proferido)
   - deposito recursal levantado pelo beneficiario (mitigante drenado)
   Sem contrapeso explicito = Baixo.

{_REGRA_H1_COMUM}"""


def _build_regras_ouro_civel() -> str:
    """REGRAS DE OURO F/G/G.1/G.2/H/H.1 — CIVEL.

    Exemplos: Temas repetitivos STJ, Sumulas STJ (matéria contratual,
    indenizatoria, consumerista), Sumula 297 STJ (CDC aplica a bancos),
    Acao Declaratoria conexa."""
    return f"""{_REGRAS_DE_OURO_HEADER}

{_REGRAS_AD_COMUM}
{_REGRA_F_COMUM}

G. JURISPRUDENCIA (v2.2 DEPRECATED em L3, vive em L2):
   Idem nota G das outras variants. Temas repetitivos STJ / Sumulas STJ /
   Temas STF cíveis agora pesam direto em risco_processo_intermediario via
   L2 prompt v2.2 (regras J/J.1/J.2). NAO re-aplicar aqui.

H. REGRA DURA — PESO DA GARANTIA + SUSPENSAO POR CONEXO FAVORAVEL (CIVEL):
   Padrao analogo ao H fiscal mas adaptado pro contexto civel:
   cenarios onde a Execucao/Cumprimento de Sentenca esta SUSPENSO
   aguardando tramite de processo conexo com decisao FAVORAVEL ao
   Tomador (ex: Acao Declaratoria de Inexigibilidade de Debito julgada
   procedente em 1g, Acao Revisional de Contrato com tutela provisoria
   favoravel, Acao Rescisoria com efeito suspensivo), com apolice ja
   apresentada e aceita.

   Quando o conjunto:
     (i)   apolice apresentada E aceita (lifecycle_garantia tem evento
           tipo='aceitacao' SEM levantamento posterior), AND
     (ii)  processo principal (Execucao OU Cumprimento de Sentenca)
           SUSPENSO/sobrestado aguardando processo conexo, AND
     (iii) conexo tem decisao FAVORAVEL ao Tomador em vigor (mesmo 1g
           sem transito), OU processo principal extinto sem merito,
   ENTAO risco = "Baixo" — mesmo com Tema repetitivo STJ contrario
   (regra G).

   Por que: o gatilho de acionamento da apolice e a EXIGENCIA ATIVA
   de pagamento (cumprimento de sentenca em curso). Enquanto o
   cumprimento esta SUSPENSO por causa externa favoravel, NAO HA
   gatilho de curto prazo. A reversao eventual em instancia superior
   eh prospectiva — nao move risco HOJE.

   CONTRAPESO LEGITIMO pra subir pra Medio mesmo com H aplicavel:
   - apolice vencida ou em renovacao com seguradora questionavel
   - tomador em RJ com plano em risco
   - sinal explicito de retomada iminente do cumprimento (despacho
     determinando intimacao da seguradora ja proferido)
   - acordao 2g desfavoravel transitando em breve (RE/REsp ja
     admissibilidade negada)
   Sem contrapeso explicito = Baixo.

{_REGRA_H1_COMUM}"""


def _build_regras_ouro_misto() -> str:
    """REGRAS DE OURO F/G/G.1/G.2/H/H.1 — MISTO (abstrato + confidence -0.10).

    Regras condicionais: 'pra processo fiscal aplique X, pra civel Y'.
    Bullet abstrato. CONFIDENCE reduzido em 0.10 por incerteza."""
    return f"""{_REGRAS_DE_OURO_HEADER}

{_REGRAS_AD_COMUM}
{_REGRA_F_COMUM}

E. REGRA EXTRA PRA MERITO MISTO — CONFIDENCE REDUZIDO:
   Este mérito mistura >=2 tipos judiciais OU dominancia <80%. SUBTRAIA
   0.10 do confidence final que voce atribuiria normalmente. Ex: se tudo
   indica 0.85 confidence, atribua 0.75. Isso reflete a incerteza
   adicional de aplicar regras heterogeneas a processos de tipos
   diferentes.

   Justifique explicitamente na narrativa_executiva: "mérito misto
   envolve processos [fiscal e civel / trabalhista e civel / ...]
   — confidence reduzida por incerteza estrutural na agregacao".

G. JURISPRUDENCIA (v2.2 DEPRECATED em L3, vive em L2):
   Idem nota G das outras variants. Cada processo do mérito (mesmo em
   mérito misto) carrega risco_processo_intermediario JA modulado pela
   juris da sua tese via L2. Use a agregacao normal pelos N processos.
   NAO re-aplicar regras de juris aqui.

H. REGRA DURA — PESO DA GARANTIA + SUSPENSAO POR CONEXO FAVORAVEL (MISTO):
   Quando o conjunto:
     (i)   apolice apresentada E aceita (lifecycle_garantia tem evento
           tipo='aceitacao' SEM levantamento posterior) EM PELO MENOS UM
           processo do merito, AND
     (ii)  processo principal SUSPENSO/sobrestado aguardando processo
           conexo (independente do tipo), AND
     (iii) conexo tem decisao FAVORAVEL ao Tomador em vigor (mesmo 1g
           sem transito), OU processo principal extinto sem merito,
   ENTAO risco = "Baixo" — mesmo com tese contraria firmada (regra G).

   Por que: o gatilho de acionamento da apolice e a EXIGENCIA ATIVA de
   pagamento em qualquer processo. Enquanto o principal esta SUSPENSO
   por causa externa favoravel, NAO HA gatilho de curto prazo.

   CONTRAPESO LEGITIMO pra subir pra Medio:
   - apolice vencida ou em renovacao com seguradora questionavel
   - tomador em RJ com plano em risco
   - sinal explicito de retomada iminente em qualquer processo
   Sem contrapeso explicito = Baixo.

{_REGRA_H1_COMUM}"""


# ─── Variant assembly (per tipo_judicial) ──────────────────────────────────


_VARIANT_BLOCKS = {
    "fiscal": (_build_escala_fiscal, _build_decisao_processual_fiscal, _build_regras_ouro_fiscal),
    "trabalhista": (_build_escala_trabalhista, _build_decisao_processual_trabalhista, _build_regras_ouro_trabalhista),
    "civel": (_build_escala_civel, _build_decisao_processual_civel, _build_regras_ouro_civel),
    "misto": (_build_escala_misto, _build_decisao_processual_misto, _build_regras_ouro_misto),
}


def _build_rules(tipo: str) -> str:
    """Assembla rules block do `tipo` dominante: escala + decisao processual
    + justifique + field instructions + regras de ouro.

    Misto adiciona Regra E (-0.10 confidence) via _build_regras_ouro_misto."""
    escala, decisao, regras = _VARIANT_BLOCKS[tipo]
    return "\n\n".join([
        escala(),
        decisao(),
        _build_justifique_subida(),
        _build_field_instructions(),
        regras(),
    ])


# ─── Main prompt builder ───────────────────────────────────────────────────


# PR6 Architecture D — A/B test buckets do L3.
# Cada bucket eh um experimento independente: roda L3 N vezes em paralelo,
# cada call usa instrucao especifica de qual sinal priorizar. Resultados
# persistidos em card['l3_ab_test'][bucket] pra comparacao com Poletto
# ground truth + selecao do vencedor.
AB_TEST_BUCKETS = ("factual_only", "juris_only", "mixed", "derived_only")


def _build_ab_test_bucket_block(
    bucket: str | None,
    derived_aggregate_hint: str | None = None,
) -> str:
    """Bloco com instrucao por bucket A/B test (PR6 Architecture D).

    Quando bucket=None: retorna string vazia (legacy single-prompt cascade).
    Quando bucket presente: injeta instrucao explicita de qual sinal usar/
    ignorar pro card['risco'] final.

    PR6 bugfix 2026-05-31: `derived_only` requer renderizacao explicita do
    `derived_aggregate_hint` no texto do prompt — antes citava apenas o
    NOME do campo (`derived_aggregate_hint`), nao o VALOR. LLM nao tinha
    acesso ao valor injetado em outra parte do payload, entao calculava
    proprio veredito (efetivamente == mixed).
    """
    if not bucket:
        return ""
    if bucket == "factual_only":
        return (
            "\n<ab_test_bucket name=\"factual_only\">\n"
            "EXPERIMENTO A/B (Architecture D PR6) — bucket FACTUAL_ONLY:\n"
            "  Pra `risco` final do merito, considere APENAS:\n"
            "    - processo_syntheses[].risco_factual\n"
            "    - processo_syntheses[].estado_processual\n"
            "    - processo_syntheses[].decisao_vigente\n"
            "    - processo_syntheses[].lifecycle_garantia\n"
            "    - processo_syntheses[].probabilidade_exito (Matriz Daycoval)\n"
            "  IGNORE COMPLETAMENTE:\n"
            "    - processo_syntheses[].risco_jurisprudencial\n"
            "    - tese_jurisprudencia (qualquer fonte)\n"
            "    - paradigmas_curados (NAO use sinal de tese)\n"
            "  Justifique em `contribuicao_no_risco` que ignorou juris por design.\n"
            "  Quando risco_factual = Indeterminado em todos procs -> emit 'Indeterminado'\n"
            "  (NAO chute Baixo por default).\n"
            "</ab_test_bucket>\n"
        )
    if bucket == "juris_only":
        return (
            "\n<ab_test_bucket name=\"juris_only\">\n"
            "EXPERIMENTO A/B (Architecture D PR6) — bucket JURIS_ONLY:\n"
            "  Pra `risco` final do merito, considere APENAS:\n"
            "    - processo_syntheses[].risco_jurisprudencial\n"
            "    - tese_jurisprudencia (interna + paradigmas curados)\n"
            "    - top_decisions externas (quando presentes nos processo_syntheses)\n"
            "  IGNORE COMPLETAMENTE:\n"
            "    - processo_syntheses[].risco_factual\n"
            "    - estado_processual + decisao_vigente + lifecycle\n"
            "    - probabilidade_exito (Matriz Daycoval)\n"
            "  Quando risco_jurisprudencial = Indeterminado em todos procs OU sem\n"
            "  tese mapeada -> emit 'Indeterminado' (NAO chute Baixo).\n"
            "  Justifique em `contribuicao_no_risco` que ignorou estado por design.\n"
            "</ab_test_bucket>\n"
        )
    if bucket == "mixed":
        return (
            "\n<ab_test_bucket name=\"mixed\">\n"
            "EXPERIMENTO A/B (Architecture D PR6) — bucket MIXED (legacy):\n"
            "  Considere TODOS os sinais (factual + juris + paradigmas + estado +\n"
            "  Matriz Daycoval). Mesma logica do prompt L3 pre-PR6 — esta variant\n"
            "  serve como baseline pra comparar contra factual_only/juris_only/\n"
            "  derived_only. Aplique todas regras anti-falso-alto + bloqueio Daycoval\n"
            "  + templates Poletto + paradigmas como em producao atual.\n"
            "</ab_test_bucket>\n"
        )
    if bucket == "derived_only":
        # PR6 bugfix: render o VALOR do hint inline (antes citava apenas nome
        # do campo, LLM nao via valor real -> calculava proprio veredito).
        hint = (derived_aggregate_hint or "Indeterminado").strip()
        return (
            "\n<ab_test_bucket name=\"derived_only\">\n"
            "EXPERIMENTO A/B (Architecture D PR6) — bucket DERIVED_ONLY:\n"
            "\n"
            f"  >>> RISCO PRE-CALCULADO PELA MATRIZ DETERM (5x5): **{hint}** <<<\n"
            "\n"
            f"  Sua resposta DEVE conter EXATAMENTE: \"risco\": \"{hint}\".\n"
            "  NAO recalcule. NAO substitua. NAO emit valor diferente — mesmo\n"
            "  que voce discorde da matriz determ. Sua tarefa NAO eh classificar,\n"
            "  eh JUSTIFICAR a classificacao ja feita.\n"
            "\n"
            "  Em `probabilidade_exito_merito.contribuicao_no_risco` cite:\n"
            "    1. Qual foi o `risco_factual` agregado (do payload)\n"
            "    2. Qual foi o `risco_jurisprudencial` agregado (do payload)\n"
            f"    3. Por que a matriz determ Architecture D chegou em **{hint}**\n"
            f"       (tabela: factual_agg x jurisprudencial_agg -> {hint})\n"
            "  Padrao: 'Esta versao reflete a matriz determ Architecture D, sem\n"
            "  nuance LLM. Factual=X juris=Y -> matriz={hint}.'\n"
            "</ab_test_bucket>\n"
        )
    # Bucket desconhecido -> trate como mixed (defensive)
    return _build_ab_test_bucket_block("mixed")


def build_prompt_and_version(
    req: MeritoSynthesisRequest,
    bucket: str | None = None,
) -> tuple[str, str]:
    """Computa (prompt, prompt_version) compartilhando o mesmo tipo dominante.

    Single source of truth pro dispatch — garante que `prompt_version` em
    `leads.engine_llm_calls` reflete a variant que efetivamente rodou
    (sem drift risk se alguem mudar o router no futuro).

    PR6: `bucket` opcional injeta bloco <ab_test_bucket> com instrucao
    especifica (factual_only / juris_only / mixed / derived_only). Quando
    None, comportamento legacy single-prompt.
    """
    tipo = _determine_tipo_dominante(req.processo_syntheses)
    # PR6 bugfix: passa derived_aggregate_hint do request pro builder do bloco
    # (antes o nome do campo era citado mas o valor nao era renderizado no
    # texto — LLM nao tinha como respeitar o hint).
    ab_test_block = _build_ab_test_bucket_block(
        bucket,
        derived_aggregate_hint=getattr(req, "derived_aggregate_hint", None),
    )
    parts = [
        _build_intro(),
        _build_glossary_roles(),
        _build_consistency_check(),
        _build_merito_header_block(req),
        _build_processos_block(req),
        _build_cdas_block(req),
        _build_aiims_block(req),
        _build_tomador_block_section(req),
        # v2.2: _build_jurisprudencia_block dropado (juris vive em L2 agora).
        _build_paradigmas_block(req),
        _build_snapshot_anterior_block(req),
        _build_protocolo_postura_default(),
        _build_bloqueio_prob_exito(),
        _build_templates_poletto(),
        _build_regras_anti_falso_alto(),
        _build_rules(tipo),
        ab_test_block,  # PR6 — injetado quando bucket != None
        _build_lembrete_final(req),
    ]
    version = _prompt_version_for(tipo)
    if bucket:
        # Suffix bucket pra rastreabilidade em engine_llm_calls.prompt_version.
        version = f"{version}__ab_{bucket}"
    return "\n\n".join(p for p in parts if p) + "\n", version


def build_merito_synthesis_prompt(
    req: MeritoSynthesisRequest,
    bucket: str | None = None,
) -> str:
    """Prompt da camada 3 - agrega 1 ou N processo_syntheses + tomador + cda/aiim
    + jurisprudencia + previous_snapshot pra computar risco do MERITO.

    Dispatch determ.:
    - >=80% fiscal -> vocab EF, Anulatoria, Tema 372/1226/DIFAL
    - >=80% trabalhista -> vocab Cumprimento, RR, Sumula TST, Tema 725
    - >=80% civel -> vocab Cumprimento de Sentenca, REsp, Tema repetitivo STJ
    - resto -> 'misto' (vocab abstrato + confidence -0.10)

    PR6 `bucket`: ver `_build_ab_test_bucket_block` doc.

    Pra telemetria com prompt_version use `build_prompt_and_version()`."""
    prompt, _ = build_prompt_and_version(req, bucket=bucket)
    return prompt

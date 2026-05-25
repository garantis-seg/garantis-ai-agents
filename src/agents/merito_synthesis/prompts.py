"""Prompt pro merito_synthesis agent (engine v6_meritos camada 3).

Output PRIMARIO da engine - risco + justificativa por merito.
"""

import json
from typing import Any

from .schemas import (
    AIIMCardMin,
    CDACardMin,
    JurisprudenciaMin,
    MeritoSynthesisRequest,
    PreviousSnapshot,
    ProcessoSynthesisMin,
    TomadorCardMin,
)


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


def build_merito_synthesis_prompt(req: MeritoSynthesisRequest) -> str:
    """Prompt da camada 3 - agrega 1 ou N processo_syntheses + tomador + cda/aiim
    + jurisprudencia + previous_snapshot pra computar risco do MERITO."""
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

    if req.processo_syntheses:
        proc_block = "\n\n".join(_summarize_processo_synthesis(p) for p in req.processo_syntheses)
    else:
        proc_block = "(SEM processo_synthesis disponivel - merito vazio ou cards faltam)"

    cdas_block = "\n".join(_summarize_cda(c) for c in (req.cdas or [])) or "  (sem CDA materializada)"
    aiims_block = "\n".join(_summarize_aiim(a) for a in (req.aiims or [])) or "  (sem AIIM/PAF materializado)"
    tomador_block = _summarize_tomador(req.tomador) if req.tomador else "  (sem tomador card)"
    jur_block = _summarize_jurisprudencia(req.jurisprudencia) if req.jurisprudencia else "  (sem jurisprudencia mapeada)"
    prev_block = _summarize_previous(req.previous_snapshot)

    return f"""Voce e analista juridico-securitario brasileiro especializado em SEGURO GARANTIA JUDICIAL.

Sua tarefa: classificar o RISCO DE ACIONAMENTO DA APOLICE pro MERITO inteiro. Voce recebe
os processo_syntheses (camada 2 ja sintetizou cada processo) + tomador + cda/aiim
+ jurisprudencia da tese + snapshot anterior (referencia historica).

ESTA E A CAMADA 3 - OUTPUT PRIMARIO. Risco aqui e o que vai pra UI/cliente.

=== GLOSSARIO ROLES EM SEGURO GARANTIA JUDICIAL (LEIA ANTES DE CLASSIFICAR) ===

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
Banco Mercantil" quando o Banco e o Tomador).

=== CONSISTENCY CHECK (obrigatorio antes de emitir output) ===

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
nesse padrao — releia, ajuste narrativa OU eleve risco.

=== MERITO ===
  {header_block}

=== PROCESSOS DO MERITO (synthesis cards) ===
{proc_block}

=== CDA / DIVIDAS ATIVAS ===
{cdas_block}

=== AIIM / PAFs ADMINISTRATIVOS ===
{aiims_block}

=== TOMADOR (historico CNPJ basico) ===
{tomador_block}

=== JURISPRUDENCIA DA TESE ===
  {jur_block}

  Glossario `resultado_majoritario` (vigente desde 2026-05-25):
  - pro_contribuinte_firmado: tese STF/STJ vinculante, favoravel ao Tomador (EMPURRA Baixo)
  - pro_fazenda_firmado: tese STF/STJ vinculante, desfavoravel ao Tomador (EMPURRA Alto)
  - oscilante: decisoes divididas entre turmas/instancias — sem majoritario claro
    (NAO move risco; governado pelo estado da causa)
  - pendente_julgamento_superior: tema afetado, aguarda STF/STJ
    (estado atual domina, MAS narrativa deve citar julgamento pendente como risco prospectivo)
  - tese_nova: sem historico significativo (governado pelo estado, baixa confianca)
  - nao_classificada: catch-all generico, sem mapeamento juridico especifico
    (governado pelo estado; FLAG na narrativa que falta tese canonica)

  OBS: campo pode vir com multiplos valores comma-separated (string_agg de rows multiplas).
  Considere o sinal mais forte na precedencia:
  firmado > oscilante > pendente > tese_nova > nao_classificada.

=== SNAPSHOT ANTERIOR (referencia historica — engine v6 nao usa hoje pra trajetoria; informativo) ===
{prev_block}

=== PROTOCOLO DE RISCO BASE (CRITICA — leia antes de classificar risco) ===

POSTURA: o gatilho de acionamento da apolice de seguro garantia eh a
EXECUCAO FISCAL ATIVA exigir pagamento do Tomador (intimacao pra pagar,
penhora, levantamento). Sem gatilho concreto, NAO HA risco imediato.

DEFAULT = "Baixo". So sobe pra Medio/Alto/Altissimo com SINAL EXPLICITO
documentado nos cards. NUNCA usar "Medio" como zona-cinza/cauteloso.

ESCALA EXPLICITA (em ordem crescente de severidade — primeiro nivel
que CASE, escolha; senao continue Baixo):

[ALTISSIMO] gatilho de acionamento JA disparado:
- transito em julgado CERTIFICADO desfavoravel + execucao ativa
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
- execucao suspensa por causa externa favoravel (regra H)
- tese pro_contribuinte_firmado em vigor (regra G.1)

REGRA DURA — DECISAO PROCESSUAL NAO MOVE RISCO:

Eventos PROCESSUAIS NAO equivalem a decisao desfavoravel de merito,
mesmo se transitados em julgado. NAO sobem risco — quando vier do L2
como decisao_vigente.sentido='desfavoravel', RECLASSIFIQUE pra neutro
porque o L2 confundiu processual com merito.

Lista NAO-EXAUSTIVA de eventos processuais (NAO movem risco):
- Agravo de instrumento (provido OU desprovido) — recurso sobre decisao
  interlocutoria; NAO julga merito da causa.
- Excecao de pre-executividade (acolhida OU rejeitada) — defesa preliminar
  sobre admissibilidade; NAO decide o credito tributario.
- Embargos de declaracao (acolhidos OU rejeitados) — esclarecimento de
  decisao anterior; NAO eh novo julgamento de merito.
- Juizo de admissibilidade de REsp/RE/Agravo Interno em REsp (positivo
  OU negativo) — porta de entrada do recurso superior; NAO decide
  merito. "TST negou seguimento ao RR" eh processual, nao desfavoravel
  de merito.
- Revogacao de efeito suspensivo de recurso — processual sobre
  tramitacao; abre porta pra Fazenda agir mas NAO consolida divida.
- Arquivamento provisorio, suspensao processual, baixa administrativa
  — atos de tramitacao.

SO movem risco (sobem pra Medio/Alto/Altissimo) decisoes DE MERITO
sobre o CONTEUDO da causa:
- Sentenca de procedencia/improcedencia em 1g
- Acordao de provimento/desprovimento do recurso de apelacao em 2g
- Acordao do STJ/STF que reforma OU mantem o merito ja julgado
- Transito em julgado da decisao de merito (nao de processual)

TESTE PRA DUVIDA: olhe o que a decisao DECIDIU.
- Decidiu sobre o credito/obrigacao/relacao juridica material? -> MERITO
- Decidiu sobre como o processo deve tramitar (recurso cabe, defesa
  cabe, prazo, suspensao)? -> PROCESSUAL = nao move risco.

Quando em duvida (decisao ambigua), NAO suba — fique em Baixo.
False negative (deixar Baixo erradamente) eh menos danoso que false
positive (atribuir Alto pra mov processual + cliente recebe alerta
indevido).

REGRA DURA — JUSTIFIQUE A SUBIDA:
Pra atribuir Medio/Alto/Altissimo, a justificativa DEVE citar
explicitamente:
1. QUAL processo carrega o sinal explicito (CNJ)
2. QUAL evento concreto (data + tipo: sentenca/transito/intimacao/penhora)
3. POR QUE encaixa no nivel escolhido (referencia ao bullet da escala)
4. CONFIRMAR que NAO eh decisao processual (vide regra acima)

Sem esses 4 itens citados na narrativa, a classificacao DEVE ser Baixo.
"Risco intermediario por sinais ambiguos" NAO eh argumento valido — eh
sinal de Baixo (sem evidencia explicita) OU classificacao indevida.

=== INSTRUCOES POR CAMPO ===

1. risco (UM dos 4 niveis): aplique o PROTOCOLO DE RISCO BASE acima.
   Default = Baixo. So sobe com sinal explicito (decisao desfavoravel
   transitada, intimacao seguradora, penhora, tese pro_fazenda_firmado
   contraria, etc — vide escala completa).

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
   b) breakdown_por_processo: lista com {{processo_numero, role, classificacao, score,
      peso_aplicado, valor_em_disputa}} pra audit.
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
    ref = processo_numero, mov_id, cda_number, cnpj_basico, etc.

=== REGRAS DE OURO ===

A. NAO INVENTE. Se nenhum processo_synthesis tem decisao_vigente, decisao_atual.sentido=null.
B. Tomador em RJ NAO sobe risco automaticamente. RJ pode SUSPENDER o processo (Baixo).
   Mas se ha processo com decisao desfavoravel TRANSITADA + tomador em RJ -> Altissimo.
C. CDA/AIIM contam pra magnitude do valor em disputa MAS nao mudam o risco diretamente -
   sao contexto descritivo. Risco vem do ESTADO DOS PROCESSOS.
D. Peca-pivo do merito pode ser de CONEXO (nao do principal). Ex: anulatória conexa
   julgou improcedente -> isso e pivo mesmo se principal e Embargos sem sentenca.
F. PROBABILIDADE DE EXITO (Daycoval) E INPUT FORTE PRO RISCO, NAO SUBSTITUI:
   - prob_exito agregada ALTA (>= 0.85, "provavel") -> EMPURRA risco pra BAIXO
     (mas nao supera trans em julgado desfavoravel — esse e Altissimo independente)
   - prob_exito BAIXA (< 0.20, "remota") -> EMPURRA risco pra ALTO
     (mesmo sem decisao desfavoravel ainda, pq a perda eventual e provavel)
   - prob_exito MEDIA (0.20-0.85) -> deixa o risco governado pelo estado atual
     (decisao_vigente, lifecycle_garantia, etc.)
   - A `contribuicao_no_risco` deve EXPLICAR essa influencia em 1 frase.

G. REGRA DURA — TESE STF/STJ FIRMADA CONTRA TOMADOR PREVALECE SOBRE 1g FAVORAVEL:
   Quando o conjunto:
     (i)  jurisprudencia.resultado_majoritario contem 'pro_fazenda_firmado'
          (tese STF/STJ transitada — repetitivo/repercussao geral), AND
     (ii) prob_exito agregada = "remota" (Daycoval matriz), AND
     (iii) decisao_vigente 1g favoravel ao Tomador SEM transito em julgado
           (apelacao/agravo/RE/REsp pendente),
   ENTAO risco = "Alto" (NAO Medio).

   Por que: tese firmada no STF/STJ vincula instancias inferiores pela ratio
   decidendi. Sentenca 1g favoravel sera revertida em juizo de admissibilidade ou
   no merito do recurso pela propria corte superior que ja decidiu o tema. O
   efeito suspensivo de apelacao NAO neutraliza esse risco — apenas adia.
   Acionamento da apolice fica praticamente certo no medio prazo (3-5 anos).

   "Medio" SO se aplica nesse cenario se houver contrapeso EXPLICITO citado:
   ex. modulacao temporal pela corte que protege o caso, distinguishing claro
   nos autos, garantia em renovacao com seguradora muito forte (so isso pra
   reduzir um patamar; nunca dois). Sem contrapeso explicito = Alto.

   Casos paradigmaticos: CSLL Tema 372 STF (Lei 7.689/88), IRPJ Stock Options
   Tema 1226 STJ, ICMS-ST repetitivo, qualquer tese pro_fazenda_firmado
   julgada com modulacao restritiva.

G.1 SINAL INVERSO — TESE FIRMADA PRO TOMADOR:
   'pro_contribuinte_firmado' eh vento de cauda forte: tese STF/STJ transitada
   favoravel ao Tomador (ex: PIS-COFINS exclusao ICMS, Tema 69 STF). EMPURRA
   risco pra Baixo mesmo se houver decisao 1g desfavoravel — reversao em
   instancia superior eh provavel pela mesma ratio decidendi. Aplicar a mesma
   logica de G em sentido inverso: sem contrapeso explicito = Baixo.

G.2 PENDENTE JULGAMENTO SUPERIOR:
   'pendente_julgamento_superior' (ex: DIFAL pre-LC 190/2022 ainda em afetacao)
   NAO move risco diretamente — governado pelo estado atual da causa. Porem
   REDUZIR confianca em 10-20% e CITAR EXPLICITAMENTE o julgamento pendente
   na narrativa_executiva + justificativa como risco prospectivo. Cliente
   precisa ouvir "ha um tema afetado que pode virar o jogo nos proximos meses".

H. REGRA DURA — PESO DA GARANTIA + SUSPENSAO POR CONEXO FAVORAVEL:
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

H.1 EXTINCAO SEM MERITO NAO CONSOLIDA DIVIDA:
   Decisao com natureza='extinto_sem_merito' (mesmo transitada) NAO julga
   o conteudo da causa — eh decisao processual. Tomador NEM ganhou NEM
   perdeu o merito. O processo extinto NAO move risco. Se houver Execucao
   Fiscal subsequente, classificar pela situacao DELA, nao pela extincao.

   Cenario tipico: Anulatoria extinta sem merito por falta de pressuposto,
   tomador segue na Execucao Fiscal. NAO classificar como Altissimo so por
   causa do "transito" da extincao — extincao sem merito eh neutra.

=== FORMATO DE SAIDA ===

Retorne APENAS JSON valido:

{{
  "merito_id": {req.merito_id},
  "merito_context": "{req.merito_context}",
  "risco": "Baixo|Medio|Alto|Altissimo",
  "justificativa": "...",
  "narrativa_executiva": "...",
  "decisao_atual": {{
    "sentido": null,
    "instancia": null,
    "natureza": null,
    "data": null,
    "processo_de_origem": null,
    "transito_certificado": false,
    "recorrida": false
  }},
  "ciclo_garantia": [],
  "valor_em_disputa_melhor_evidencia": null,
  "valor_garantia_melhor_evidencia": null,
  "peca_pivo_merito": {{
    "processo_numero": null,
    "mov_id": null,
    "data": null,
    "motivo": null
  }},
  "proximos_passos_provaveis": [],
  "probabilidade_exito_merito": {{
    "classificacao_agregada": "provavel|possivel|poucas_chances|remota",
    "score_agregado": 0.7,
    "metodo_agregacao": "media_ponderada_valor_disputa",
    "breakdown_por_processo": [
      {{"processo_numero": "...", "role": "principal|conexo",
        "classificacao": "...", "score": 0.7,
        "peso_aplicado": 1.0, "valor_em_disputa": null}}
    ],
    "contribuicao_no_risco": "..."
  }},
  "confidence": 0.7,
  "evidence_artifacts": [],
  "cards_index": {{}}
}}
"""

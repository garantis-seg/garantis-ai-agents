"""Prompt templates for risk classification agent.

Contains specialized prompts per matéria (Fiscal, Cível, Trabalhista).
Each prompt has its own risk matrix and calibration rules.
Edit the specific matéria section to tune classification for that type.
"""

# ══════════════════════════════════════════════════════════════════════════════
# FISCAL — 84% dos processos monitorados
# ══════════════════════════════════════════════════════════════════════════════

FISCAL_PROMPT = """Você é um analista jurídico especializado em seguro garantia judicial TRIBUTÁRIO/FISCAL, trabalhando para a seguradora Daycoval.
Sua tarefa é classificar o RISCO DE ACIONAMENTO de uma apólice de seguro garantia com base nos andamentos processuais.

## CRITÉRIOS DE CLASSIFICAÇÃO — FISCAL

**BAIXO:**
A) Apólice aceita nos autos pelo Juiz e Segurado para oposição de Embargos ou Ação Cautelar Antecedente/Liminar/Ação Anulatória para obtenção de Certidão Negativa de Débitos ou discussão do débito
B) Aguarda-se a decisão sobre aceitação da apólice
C) Apólice aceita na execução fiscal com embargos à execução fiscal julgados procedentes
D) Apólice aceita em execução fiscal suspensa enquanto se aguarda o trânsito em julgado de ação anulatória do débito fiscal
E) Julgamento favorável ao Tomador em segunda ou última instância

**MÉDIO:**
A) Julgamento desfavorável em 1ª instância com interposição de recurso pelo Tomador
B) Execução fiscal suspensa em razão de acordo realizado entre Tomador e Segurado para parcelamento do débito, desde que haja manutenção da garantia na modalidade execução fiscal

**ALTO:**
A) Decisão desfavorável ao Tomador em Embargos à Execução/Ação Anulatória que discute o débito, sem interposição de recurso pelo Tomador
B) Descumprimento, pelo Tomador, do acordo para parcelamento do débito garantido pela apólice

**ALTÍSSIMO:**
A) Decisão desfavorável ao Tomador transitada em julgado
B) Intimação do Tomador para pagamento do débito após o trânsito em julgado
C) Decisão determinando pagamento pela Seguradora

## REGRAS DE AJUSTE

1. **Trânsito em julgado — verifique o mérito:** Decisão FAVORÁVEL transitada = Baixo. Extinção sem mérito = Baixo. Suspensão por Tema Repetitivo STJ/STF após trânsito = Alto (não Altíssimo).
2. **Recuperação Judicial:** Agrave em pelo menos um nível. NUNCA classifique Baixo um Tomador em RJ.
3. **Conexos:** Use apenas para identificar o estágio nos critérios. Se as movimentações do conexo NÃO dizem explicitamente "improcedente" ou "desfavorável", trate como "sem decisão" (Baixo). Recurso/apelação no conexo NÃO implica decisão desfavorável.
4. **Desempate:** Quando em dúvida entre dois níveis, escolha o MAIS ALTO.
"""

# ══════════════════════════════════════════════════════════════════════════════
# CÍVEL
# ══════════════════════════════════════════════════════════════════════════════

CIVEL_PROMPT = """Você é um analista jurídico especializado em seguro garantia judicial CÍVEL, trabalhando para a seguradora Daycoval.
Sua tarefa é classificar o RISCO DE ACIONAMENTO de uma apólice de seguro garantia com base nos andamentos processuais.

## CRITÉRIOS DE CLASSIFICAÇÃO — CÍVEL

**BAIXO:**
A) Apólice aceita no cumprimento de sentença/execução de título extrajudicial para oposição de embargos pelo Tomador
B) Aguarda-se a decisão sobre aceitação da apólice
C) Apólice aceita no cumprimento de sentença/embargos à execução com julgamento procedente em favor do Tomador/Executado (êxito na discussão integral do débito)
D) Julgamento favorável ao Tomador em segunda ou última instância

**MÉDIO:**
A) Aceita a garantia no processo, com julgamento desfavorável total ou parcial ao Tomador em 1ª instância na execução/cumprimento de sentença, com interposição de recurso de apelação e atribuição de efeito suspensivo
B) Homologação de acordo para parcelamento do valor garantido na apólice, com obrigatoriedade de manutenção da garantia

**ALTO:**
A) Decisão desfavorável ao Tomador em Embargos à Execução/Cumprimento de Sentença que discute o débito, com prazo para interposição de recurso
B) Descumprimento, pelo Tomador, do acordo para parcelamento da dívida garantida pela apólice

**ALTÍSSIMO:**
A) Decisão desfavorável ao Tomador em Embargos à Execução/Cumprimento de Sentença que discute o débito, sem interposição de recurso
B) Intimação do Tomador para pagamento da condenação
C) Decisão determinando pagamento pela Seguradora

## REGRAS DE AJUSTE

1. **Trânsito em julgado — verifique o mérito:** Decisão FAVORÁVEL transitada = Baixo. Extinção sem mérito = Baixo.
2. **Recuperação Judicial:** Agrave em pelo menos um nível. NUNCA classifique Baixo um Tomador em RJ.
3. **Conexos:** Use apenas para identificar o estágio. Sem menção explícita a "improcedente"/"desfavorável" = sem decisão (Baixo).
4. **Desempate:** Quando em dúvida, escolha o MAIS ALTO.
"""

# ══════════════════════════════════════════════════════════════════════════════
# TRABALHISTA
# ══════════════════════════════════════════════════════════════════════════════

TRABALHISTA_PROMPT = """Você é um analista jurídico especializado em seguro garantia judicial TRABALHISTA, trabalhando para a seguradora Daycoval.
Sua tarefa é classificar o RISCO DE ACIONAMENTO de uma apólice de seguro garantia com base nos andamentos processuais.

## CRITÉRIOS DE CLASSIFICAÇÃO — TRABALHISTA

**BAIXO:**
A) Apólice aceita na Execução Trabalhista para apresentação de impugnação do cálculo pelo Tomador
B) Aguarda-se a decisão sobre aceitação da apólice
C) Apólice aceita na impugnação com julgamento procedente em favor do Tomador (êxito em relação ao cálculo da condenação)
D) Julgamento favorável ao Tomador em segunda ou última instância

**MÉDIO:**
A) Aceita a garantia no processo, com julgamento desfavorável ao Tomador em 1ª instância na impugnação, com interposição de recurso (agravo de petição) e atribuição de efeito suspensivo
B) Homologação de acordo para parcelamento do valor garantido na apólice, com obrigatoriedade de manutenção da garantia

**ALTO:**
A) Decisão desfavorável ao Tomador em impugnação à execução que discute o débito, com prazo para interposição de recurso
B) Descumprimento, pelo Tomador, do acordo para parcelamento da dívida garantida pela apólice

**ALTÍSSIMO:**
A) Decisão desfavorável ao Tomador em impugnação à execução que discute o débito, sem interposição de recurso
B) Intimação do Tomador para pagamento da condenação
C) Decisão determinando pagamento pela Seguradora

## REGRAS DE AJUSTE

1. **Trânsito em julgado — verifique o mérito:** Decisão FAVORÁVEL transitada = Baixo. Extinção sem mérito = Baixo.
2. **Recuperação Judicial:** Agrave em pelo menos um nível. NUNCA classifique Baixo um Tomador em RJ.
3. **Conexos:** Use apenas para identificar o estágio. Sem menção explícita a "improcedente"/"desfavorável" = sem decisão (Baixo).
4. **Desempate:** Quando em dúvida, escolha o MAIS ALTO.
"""

# ══════════════════════════════════════════════════════════════════════════════
# Mapping matéria → prompt
# ══════════════════════════════════════════════════════════════════════════════

_MATERIA_PROMPTS = {
    "tributário": FISCAL_PROMPT,
    "tributario": FISCAL_PROMPT,
    "fiscal": FISCAL_PROMPT,
    "cível": CIVEL_PROMPT,
    "civel": CIVEL_PROMPT,
    "trabalhista": TRABALHISTA_PROMPT,
}


def build_risk_prompt(
    processo_data: dict,
    movimentacoes: list[dict],
    cluster_processos: list[dict] | None = None,
) -> str:
    """Build the classification prompt with process data, movements, and cluster.

    Selects the specialized prompt based on matéria (Fiscal/Cível/Trabalhista).

    Args:
        processo_data: Dict with keys nr_processo, materia, fase, vl_is_total,
                       nm_tomador, rating_tomador, cnpj_tomador
        movimentacoes: List of movement dicts from Escavador API (data, tipo, conteudo)
        cluster_processos: Optional list of related processes with their movements
    """
    # Select specialized prompt by matéria
    materia = (processo_data.get("materia") or "").lower().strip()
    specialist_prompt = _MATERIA_PROMPTS.get(materia, FISCAL_PROMPT)

    # Format movements chronologically (most recent first, max 10)
    movs_lines = []
    for m in movimentacoes[:10]:
        data = m.get("data", "s/d")
        tipo = m.get("tipo", "")
        conteudo = m.get("conteudo", "")
        if conteudo:
            conteudo = conteudo[:500]
        movs_lines.append(f"[{data}] {tipo}: {conteudo}")

    movs_text = "\n".join(movs_lines) if movs_lines else "Nenhuma movimentação disponível."

    # Format IS value
    is_val = processo_data.get("vl_is_total")
    is_str = f"R$ {is_val:,.2f}" if is_val else "Não informado"

    # Build cluster section if available
    cluster_text = ""
    if cluster_processos:
        parts = []
        for cp in cluster_processos:
            num = cp.get("numero", "")
            tipo = cp.get("tipo_relacao", "relacionado")
            movs = cp.get("movimentacoes", [])
            if movs:
                lines = [
                    f"  [{m.get('data', 's/d')}] {m.get('tipo', '')}: {m.get('conteudo', '')[:150]}"
                    for m in movs[:5]
                ]
                parts.append(f"### {num} ({tipo})\n" + "\n".join(lines))
            else:
                parts.append(f"### {num} ({tipo})\n  Sem movimentações disponíveis")

        cluster_text = (
            f"\n## PROCESSOS CONEXOS\n"
            f"Processos relacionados ao principal. Use para identificar o estágio nos critérios.\n\n"
            + "\n\n".join(parts)
        )

    return f"""{specialist_prompt}

## INSTRUÇÕES

Analise as movimentações processuais abaixo e classifique o risco:

1. Identifique em QUAL critério acima o processo se enquadra (cite a letra, ex: "Baixo C")
2. Classifique: Baixo, Medio, Alto ou Altissimo
3. Justifique citando o critério específico e a situação processual
4. Recomende ação prática:
   - Alto/Altíssimo: "Entrar em contato com o Tomador para avaliação de risco"
   - Baixo/Médio: "Manter o acompanhamento regular do processo"
5. No resumo, liste os 3-5 andamentos mais relevantes com datas

## DADOS DO PROCESSO

- Número: {processo_data.get('nr_processo', 'N/A')}
- Matéria: {processo_data.get('materia', 'N/A')}
- Fase: {processo_data.get('fase', 'N/A')}
- Importância Segurada (IS): {is_str}
- Tomador: {processo_data.get('nm_tomador', 'N/A')}
- Rating: {processo_data.get('rating_tomador', 'N/A')}

## ANDAMENTOS PROCESSUAIS (mais recentes primeiro)

{movs_text}
{cluster_text}

Responda EXCLUSIVAMENTE em JSON válido com os campos: risco, justificativa, recomendacao, andamentos_resumo."""


# ══════════════════════════════════════════════════════════════════════════════
# SUMARIZADOR — Etapa 1: extrai fatos estruturados das movimentações
# ══════════════════════════════════════════════════════════════════════════════

SUMMARIZER_PROMPT = """Você é um analista jurídico. Analise as movimentações processuais abaixo e extraia os FATOS RELEVANTES para avaliar o risco de uma apólice de seguro garantia.

Foque em identificar:
- Se houve embargos/impugnação e qual o resultado (procedentes, improcedentes, parcialmente procedentes)
- Se há ação anulatória ou mandado de segurança paralelo e qual o resultado
- Em qual instância está o processo (1ª, 2ª, STJ/STF/TST)
- Se há recurso pendente e qual tipo (apelação, RE, REsp, agravo, AIRR)
- Se houve trânsito em julgado e de que decisão (favorável ou desfavorável ao tomador)
- Se há acordo/parcelamento e se está sendo cumprido
- Se o processo está suspenso e por qual motivo
- Se há determinação de pagamento ou intimação para pagamento

## DADOS DO PROCESSO

- Número: {nr_processo}
- Matéria: {materia}
- Fase: {fase}
- Tomador: {nm_tomador}

## ANDAMENTOS PROCESSUAIS (mais recentes primeiro)

{movs_text}
{cluster_text}

Responda EXCLUSIVAMENTE em JSON válido:
{{
  "embargos_status": "nao_opostos | pendentes | procedentes | improcedentes | parcialmente_procedentes",
  "embargos_instancia": "1a | 2a | superior | null",
  "embargos_recurso_pendente": true/false,
  "embargos_resultado_2a_instancia": "mantido_desfavoravel | reformado_favoravel | pendente | null",
  "acao_anulatoria_status": "inexistente | sem_decisao | favoravel | desfavoravel",
  "acao_anulatoria_recurso_pendente": true/false,
  "transito_em_julgado": true/false,
  "transito_favoravel_tomador": true/false/null,
  "acordo_parcelamento": "inexistente | vigente | descumprido",
  "processo_suspenso": true/false,
  "motivo_suspensao": "string ou null",
  "intimacao_pagamento": true/false,
  "determinacao_pagamento_seguradora": true/false,
  "resumo_situacao": "1-2 frases descrevendo a situação processual atual"
}}"""


def build_summary_prompt(
    processo_data: dict,
    movimentacoes: list[dict],
    cluster_processos: list[dict] | None = None,
) -> str:
    """Build the summarizer prompt (step 1 of 2-step classification)."""
    # Format movements
    movs_lines = []
    for m in movimentacoes[:10]:
        data = m.get("data", "s/d")
        tipo = m.get("tipo", "")
        conteudo = m.get("conteudo", "")
        if conteudo:
            conteudo = conteudo[:500]
        movs_lines.append(f"[{data}] {tipo}: {conteudo}")

    movs_text = "\n".join(movs_lines) if movs_lines else "Nenhuma movimentação disponível."

    # Cluster
    cluster_text = ""
    if cluster_processos:
        parts = []
        for cp in cluster_processos:
            num = cp.get("numero", "")
            tipo = cp.get("tipo_relacao", "relacionado")
            movs = cp.get("movimentacoes", [])
            if movs:
                lines = [
                    f"  [{m.get('data', 's/d')}] {m.get('tipo', '')}: {m.get('conteudo', '')[:150]}"
                    for m in movs[:5]
                ]
                parts.append(f"### {num} ({tipo})\n" + "\n".join(lines))
            else:
                parts.append(f"### {num} ({tipo})\n  Sem movimentações disponíveis")
        cluster_text = (
            f"\n## PROCESSOS CONEXOS\n\n"
            + "\n\n".join(parts)
        )

    return SUMMARIZER_PROMPT.format(
        nr_processo=processo_data.get("nr_processo", "N/A"),
        materia=processo_data.get("materia", "N/A"),
        fase=processo_data.get("fase", "N/A"),
        nm_tomador=processo_data.get("nm_tomador", "N/A"),
        movs_text=movs_text,
        cluster_text=cluster_text,
    )


def build_classification_from_summary_prompt(
    processo_data: dict,
    summary: dict,
) -> str:
    """Build the classifier prompt using structured summary (step 2 of 2-step)."""
    materia = (processo_data.get("materia") or "").lower().strip()
    specialist_prompt = _MATERIA_PROMPTS.get(materia, FISCAL_PROMPT)

    is_val = processo_data.get("vl_is_total")
    is_str = f"R$ {is_val:,.2f}" if is_val else "Não informado"

    # Format summary as readable text
    summary_text = f"""- Embargos/Impugnação: {summary.get('embargos_status', 'desconhecido')}
- Instância dos embargos: {summary.get('embargos_instancia', 'N/A')}
- Recurso pendente nos embargos: {summary.get('embargos_recurso_pendente', 'N/A')}
- Resultado em 2ª instância: {summary.get('embargos_resultado_2a_instancia', 'N/A')}
- Ação Anulatória/MS: {summary.get('acao_anulatoria_status', 'inexistente')}
- Recurso pendente na ação anulatória: {summary.get('acao_anulatoria_recurso_pendente', 'N/A')}
- Trânsito em julgado: {summary.get('transito_em_julgado', False)}
- Trânsito favorável ao Tomador: {summary.get('transito_favoravel_tomador', 'N/A')}
- Acordo/Parcelamento: {summary.get('acordo_parcelamento', 'inexistente')}
- Processo suspenso: {summary.get('processo_suspenso', False)} ({summary.get('motivo_suspensao', '')})
- Intimação para pagamento: {summary.get('intimacao_pagamento', False)}
- Determinação de pagamento pela seguradora: {summary.get('determinacao_pagamento_seguradora', False)}
- Situação atual: {summary.get('resumo_situacao', 'N/A')}"""

    return f"""{specialist_prompt}

## INSTRUÇÕES

Com base na ANÁLISE PROCESSUAL ESTRUTURADA abaixo, classifique o risco:

1. Identifique em QUAL critério acima o processo se enquadra (cite a letra, ex: "Baixo C")
2. Classifique: Baixo, Medio, Alto ou Altissimo
3. Justifique citando o critério específico e a situação processual
4. Recomende ação prática:
   - Alto/Altíssimo: "Entrar em contato com o Tomador para avaliação de risco"
   - Baixo/Médio: "Manter o acompanhamento regular do processo"

## DADOS DO PROCESSO

- Número: {processo_data.get('nr_processo', 'N/A')}
- Matéria: {processo_data.get('materia', 'N/A')}
- Fase: {processo_data.get('fase', 'N/A')}
- Importância Segurada (IS): {is_str}
- Tomador: {processo_data.get('nm_tomador', 'N/A')}
- Rating: {processo_data.get('rating_tomador', 'N/A')}

## ANÁLISE PROCESSUAL ESTRUTURADA

{summary_text}

Responda EXCLUSIVAMENTE em JSON válido com os campos: risco, justificativa, recomendacao, andamentos_resumo."""

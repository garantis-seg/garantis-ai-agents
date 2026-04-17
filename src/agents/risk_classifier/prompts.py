"""Prompt templates for risk classification agent.

Contains the risk matrix and classification criteria.
Edit RISK_MATRIX and CALIBRATION_RULES to tune the LLM classification.
"""

# ══════════════════════════════════════════════════════════════════════════════
# MATRIZ DE RISCO — edite os critérios abaixo para cada matéria e nível
# ══════════════════════════════════════════════════════════════════════════════

RISK_MATRIX = """
## MATRIZ DE CLASSIFICAÇÃO DE RISCO — SEGURO GARANTIA JUDICIAL
## (Critérios expandidos conforme padrão do escritório Poletto Possamai)

### FISCAL

**BAIXO:**
A) Apólice aceita nos autos para oposição de Embargos ou Ação Cautelar/Anulatória para obtenção de CND ou discussão do débito
B) Aguarda-se a decisão sobre aceitação da apólice
C) Embargos à Execução julgados PROCEDENTES (total ou parcialmente) — Tomador venceu a discussão do débito
D) Embargos julgados procedentes para realização de novos cálculos ou retorno à liquidação (favorável ao Tomador)
E) Execução fiscal suspensa aguardando Ação Anulatória/MS SEM decisão de 1ª instância
F) Execução fiscal suspensa aguardando Ação Anulatória/MS COM resultado favorável ao Tomador
G) Julgamento favorável ao Tomador em segunda ou última instância
H) Sentença parcialmente procedente ao Tomador, com suspensão da exigibilidade

**MÉDIO:**
A) Embargos à Execução julgados IMPROCEDENTES com recurso de apelação interposto (pendente de julgamento)
B) Embargos à Execução julgados improcedentes com prazo para recurso em curso
C) Execução fiscal suspensa aguardando Ação Anulatória/MS COM sentença desfavorável ao Tomador e recurso de apelação pendente
D) Execução fiscal suspensa em razão de acordo judicial para parcelamento do débito, com manutenção da garantia

**ALTO:**
A) Embargos à Execução julgados improcedentes com resultado desfavorável MANTIDO em 2ª instância (ainda não transitado em julgado)
B) Ação Anulatória/MS com sentença desfavorável ao Tomador mantida em 2ª instância (sem trânsito)
C) Decisão desfavorável em 2ª instância com RE/REsp/Agravo pendente (sem efeito suspensivo automático)
D) Decisão desfavorável ao Tomador em Embargos/Ação Anulatória sem interposição de recurso pelo Tomador
E) Descumprimento, pelo Tomador, do acordo para parcelamento do débito garantido pela apólice

**ALTÍSSIMO:**
A) Decisão desfavorável ao Tomador transitada em julgado
B) Intimação do Tomador para pagamento do débito após o trânsito em julgado
C) Decisão determinando pagamento pela Seguradora

---

### CÍVEL

**BAIXO:**
A) Apólice aceita no cumprimento de sentença/execução de título extrajudicial para oposição de embargos pelo Tomador
B) Aguarda-se a decisão sobre aceitação da apólice
C) Embargos à execução julgados procedentes em favor do Tomador (êxito na discussão do débito)
D) Embargos procedentes para realização de novos cálculos ou desoneração parcial
E) Julgamento favorável ao Tomador em segunda ou última instância

**MÉDIO:**
A) Julgamento desfavorável ao Tomador em 1ª instância com recurso de apelação e efeito suspensivo
B) Embargos julgados improcedentes com recurso de apelação pendente
C) Homologação de acordo para parcelamento com obrigatoriedade de manutenção da garantia

**ALTO:**
A) Embargos julgados improcedentes com resultado mantido em 2ª instância (sem trânsito)
B) Impugnação julgada improcedente com recursos sem efeito suspensivo
C) Decisão desfavorável com prazo para recurso em curso
D) Descumprimento do acordo para parcelamento da dívida garantida

**ALTÍSSIMO:**
A) Decisão desfavorável ao Tomador sem interposição de recurso
B) Intimação do Tomador para pagamento da condenação
C) Decisão determinando pagamento pela Seguradora

---

### TRABALHISTA

**BAIXO:**
A) Apólice aceita na Execução Trabalhista para apresentação de impugnação do cálculo pelo Tomador
B) Aguarda-se a decisão sobre aceitação da apólice
C) Impugnação julgada procedente em favor do Tomador (êxito no cálculo da condenação)
D) Embargos procedentes para realização de novos cálculos na liquidação
E) Julgamento favorável ao Tomador em segunda ou última instância

**MÉDIO:**
A) Julgamento desfavorável ao Tomador em 1ª instância na impugnação, com recurso (agravo de petição) e efeito suspensivo
B) Embargos/impugnação julgados improcedentes com recurso pendente
C) Homologação de acordo para parcelamento com manutenção da garantia

**ALTO:**
A) Embargos/impugnação julgados improcedentes com resultado mantido em 2ª instância
B) Acórdão desfavorável nos embargos com ação principal transitada em julgado
C) Decisão desfavorável com prazo para recurso em curso
D) Descumprimento do acordo para parcelamento

**ALTÍSSIMO:**
A) Decisão desfavorável sem interposição de recurso
B) Intimação do Tomador para pagamento da condenação
C) Decisão determinando pagamento pela Seguradora
"""

# ══════════════════════════════════════════════════════════════════════════════
# REGRAS DE CALIBRAÇÃO — edite aqui para ajustar o comportamento da LLM
#
# Cada regra é uma instrução direta que a LLM segue ao classificar.
# Adicione, remova ou modifique regras conforme necessário.
# ══════════════════════════════════════════════════════════════════════════════

CALIBRATION_RULES = """
## REGRAS DE AJUSTE (aplique APÓS enquadrar na matriz acima)

### 1. TRÂNSITO EM JULGADO — VERIFIQUE O MÉRITO
"Trânsito em julgado" NÃO é automaticamente Altíssimo. Verifique O QUE transitou:
- Decisão DESFAVORÁVEL transitada = Altíssimo
- Decisão FAVORÁVEL transitada = Baixo
- Extinção sem resolução de mérito = Baixo
- Se suspenso por Tema Repetitivo STJ/STF após trânsito = Alto (não Altíssimo)

### 2. RECUPERAÇÃO JUDICIAL
Se o nome do Tomador contém "RECUPERAÇÃO JUDICIAL" ou "EM RJ":
- Agrave em PELO MENOS um nível (Baixo→Médio, Médio→Alto, Alto→Altíssimo)
- NUNCA classifique Baixo um Tomador em RJ

### 3. PROCESSOS CONEXOS (CLUSTER)
Se houver movimentações de processos conexos:
- Use APENAS para identificar o estágio na matriz, não para agravar
- Se as movimentações do conexo NÃO dizem explicitamente "improcedente" ou "desfavorável", trate como "sem decisão de mérito" (Baixo)
- Recurso/apelação no conexo NÃO implica decisão desfavorável

### 4. REGRA DE DESEMPATE
Quando em dúvida entre dois níveis adjacentes, escolha o MAIS ALTO.

### 5. RECOMENDAÇÕES
- Alto/Altíssimo: "Entrar em contato com o Tomador para avaliação de risco"
- Baixo/Médio: "Manter o acompanhamento regular do processo"
"""

# ══════════════════════════════════════════════════════════════════════════════
# EXEMPLOS DE REFERÊNCIA — do escritório Poletto Possamai
# ══════════════════════════════════════════════════════════════════════════════

POLETTO_EXAMPLES = """
## EXEMPLOS DE CLASSIFICAÇÃO (referência do escritório Poletto Possamai)

### ALTÍSSIMO — Tributário
Justificativa: "Apólice apresentada em Ação Anulatória de débito fiscal ou Mandado de Segurança com sentença desfavorável ao Tomador transitada em julgado, ainda que parcialmente."
Recomendação: "Entrar em contato com o Tomador e questionar como pagará o débito"

### ALTO — Tributário
Justificativa: "Apólice aceita em Execução Fiscal com Embargos à Execução julgados improcedentes (ou parcialmente procedentes) e resultado desfavorável ao Tomador mantido em 2ª Instância ainda não transitado em julgado"
Recomendação: "Entrar em contato com o Tomador a fim de verificar como ele pagará o débito no caso de retomada da Execução"

### ALTO — Cível
Justificativa: "Apólice apresentada em Cumprimento de Sentença para a atribuição de efeito suspensivo à impugnação. Impugnação julgada improcedente com interposição de recursos sem atribuição de efeito suspensivo. Medidas constritivas suspensas por liminar em Agravo de Instrumento."
Recomendação: "Entrar em contato com o Tomador a fim de verificar como ele pagará o débito ou se desonerará a Seguradora"

### ALTO — Trabalhista
Justificativa: "Apólice apresentada em Cumprimento Provisório de Sentença, havendo acórdão desfavorável nos embargos à execução. A ação principal encontra-se transitada em julgado, e o tomador ainda não foi intimado para pagamento do débito."
Recomendação: "Entrar em contato com o Tomador a fim de verificar como ele pagará o débito ou se desonerará a Seguradora"

### MÉDIO — Tributário
Justificativa: "Apólice aceita em Execução Fiscal com Embargos à Execução julgados improcedentes (ou parcialmente procedentes) e prazo em curso para recorrer da sentença"
Recomendação: "Manter o acompanhamento do processo"

### MÉDIO — Trabalhista
Justificativa: "Apólice apresentada em Cumprimento Definitivo de Sentença para apresentação de embargos à execução. Embargos julgados improcedentes ou parcialmente procedentes. PEPT sendo cumprido pelo Tomador."
Recomendação: "Manter o acompanhamento do processo"

### BAIXO — Tributário
Justificativa: "Apólice aceita na execução fiscal com embargos à execução fiscal julgados procedentes. Execução fiscal suspensa aguardando trânsito em julgado."
Recomendação: "Manter o acompanhamento do processo"

### BAIXO — Cível
Justificativa: "Apólice aceita em conversão de cumprimento de liminar em perdas e danos, ainda sem sentença"
Recomendação: "Continuar a acompanhar o processo"

### BAIXO — Trabalhista
Justificativa: "Declarado adimplido o parcelamento do débito devido ao autor. Aguarda-se a manifestação da União sobre o cálculo dos débitos previdenciários para a extinção da execução."
Recomendação: "Manter o acompanhamento do processo até a extinção da execução"
"""


def build_risk_prompt(
    processo_data: dict,
    movimentacoes: list[dict],
    cluster_processos: list[dict] | None = None,
) -> str:
    """Build the classification prompt with process data, movements, and cluster.

    Args:
        processo_data: Dict with keys nr_processo, materia, fase, vl_is_total,
                       nm_tomador, rating_tomador, cnpj_tomador
        movimentacoes: List of movement dicts from Escavador API (data, tipo, conteudo)
        cluster_processos: Optional list of related processes with their movements
    """
    # Format movements chronologically (most recent first)
    movs_lines = []
    for m in movimentacoes[:20]:
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
                    for m in movs[:10]
                ]
                parts.append(f"### {num} ({tipo})\n" + "\n".join(lines))
            else:
                parts.append(f"### {num} ({tipo})\n  Sem movimentações disponíveis")

        cluster_text = (
            f"\n## CLUSTER DE PROCESSOS RELACIONADOS\n"
            f"Este processo faz parte de um cluster de {len(cluster_processos) + 1} processos relacionados.\n"
            f"Considere o contexto conjunto — decisões nos processos relacionados (embargos, ações anulatórias, recursos) "
            f"afetam DIRETAMENTE o risco deste processo principal.\n\n"
            + "\n\n".join(parts)
        )

    return f"""Você é um analista jurídico especializado em seguro garantia judicial, trabalhando para a seguradora Daycoval.
Sua tarefa é classificar o RISCO DE ACIONAMENTO de uma apólice de seguro garantia com base nos andamentos processuais mais recentes.

{RISK_MATRIX}

{CALIBRATION_RULES}

{POLETTO_EXAMPLES}

## INSTRUÇÕES

1. Leia atentamente as movimentações processuais abaixo (e do cluster, se houver)
2. Identifique a MATÉRIA do processo (Fiscal, Cível ou Trabalhista)
3. Determine o ESTÁGIO ATUAL dos embargos/impugnação/ação anulatória usando a tabela de progressão
4. Enquadre a situação atual do processo em UM dos critérios da matriz acima, correspondente à matéria correta
5. Classifique o risco como: Baixo, Medio, Alto ou Altissimo
6. Na justificativa, cite QUAL critério específico da matriz se aplica e por quê
7. Na recomendação, indique a ação prática que a equipe comercial/P&P deve tomar
8. No resumo de andamentos, liste os 3-5 eventos processuais mais relevantes em ordem cronológica

## DADOS DO PROCESSO

- Número: {processo_data.get('nr_processo', 'N/A')}
- Matéria: {processo_data.get('materia', 'N/A')}
- Fase: {processo_data.get('fase', 'N/A')}
- Importância Segurada (IS): {is_str}
- Tomador: {processo_data.get('nm_tomador', 'N/A')}
- Rating: {processo_data.get('rating_tomador', 'N/A')}

## MOVIMENTAÇÕES RECENTES (mais recentes primeiro)

{movs_text}
{cluster_text}

Responda EXCLUSIVAMENTE em JSON válido com os campos: risco, justificativa, recomendacao, andamentos_resumo."""

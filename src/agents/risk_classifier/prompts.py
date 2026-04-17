"""Prompt templates for risk classification agent.

Contains the risk matrix and classification criteria.
Edit RISK_MATRIX and CALIBRATION_RULES to tune the LLM classification.
"""

# ══════════════════════════════════════════════════════════════════════════════
# MATRIZ DE RISCO — edite os critérios abaixo para cada matéria e nível
# ══════════════════════════════════════════════════════════════════════════════

RISK_MATRIX = """
## MATRIZ DE CLASSIFICAÇÃO DE RISCO — SEGURO GARANTIA JUDICIAL

### FISCAL

**BAIXO:**
- Apólice aceita nos autos pelo Juiz e Segurado para oposição de Embargos ou Ação Cautelar Antecedente/Liminar/Ação Anulatória para obtenção de Certidão Negativa de Débitos ou discussão do débito
- Aguarda-se a decisão sobre aceitação da apólice
- Apólice aceita na execução fiscal com embargos à execução fiscal julgados procedentes
- Apólice aceita em execução fiscal suspensa enquanto se aguarda o trânsito em julgado de ação anulatória do débito fiscal
- Julgamento favorável ao Tomador em segunda ou última instância

**MÉDIO:**
- Julgamento desfavorável em 1ª Instância com interposição de recurso pelo Tomador
- Execução Fiscal suspensa em razão de acordo realizado entre Tomador e Segurado para parcelamento do débito, desde que haja manutenção da garantia na modalidade execução fiscal

**ALTO:**
- Decisão desfavorável ao Tomador em Embargos à Execução/Ação Anulatória que discute o débito, sem interposição de recurso pelo Tomador
- Descumprimento, pelo Tomador, do acordo para parcelamento do débito garantido pela apólice

**ALTÍSSIMO:**
- Decisão desfavorável ao Tomador transitada em julgado
- Intimação do Tomador para pagamento do débito após o trânsito em julgado
- Decisão determinando pagamento pela Seguradora

---

### CÍVEL

**BAIXO:**
- Apólice aceita no cumprimento de sentença/execução de título extrajudicial para oposição de embargos pelo Tomador
- Aguarda-se a decisão sobre aceitação da apólice
- Apólice aceita no cumprimento de sentença/embargos à execução com julgamento procedente em favor do Tomador/Executado (êxito na discussão integral do débito)
- Julgamento favorável ao Tomador em segunda ou última Instância

**MÉDIO:**
- Aceita a garantia no processo, com julgamento desfavorável total ou parcial ao Tomador em 1ª Instância na execução/cumprimento de sentença, com interposição de recurso de apelação e atribuição de efeito suspensivo
- Homologação de acordo para parcelamento do valor garantido na apólice, com obrigatoriedade de manutenção da garantia

**ALTO:**
- Decisão desfavorável ao Tomador em Embargos à Execução/Cumprimento de Sentença que discute o débito, com prazo para interposição de recurso
- Descumprimento, pelo Tomador, do acordo para parcelamento da dívida garantida pela apólice

**ALTÍSSIMO:**
- Decisão desfavorável ao Tomador em Embargos à Execução/Cumprimento de Sentença que discute o débito, sem interposição de recurso
- Intimação do Tomador para pagamento da condenação
- Decisão determinando pagamento pela Seguradora

---

### TRABALHISTA

**BAIXO:**
- Apólice aceita na Execução Trabalhista para apresentação de impugnação do cálculo pelo Tomador
- Aguarda-se a decisão sobre aceitação da apólice
- Apólice aceita na impugnação com julgamento procedente em favor do Tomador (êxito em relação ao cálculo da condenação)
- Julgamento favorável ao Tomador em segunda ou última instância

**MÉDIO:**
- Aceita a garantia no processo, com julgamento desfavorável ao Tomador em 1ª Instância na impugnação, com interposição de recurso (agravo de petição) e atribuição de efeito suspensivo
- Homologação de acordo para parcelamento do valor garantido na apólice, com obrigatoriedade de manutenção da garantia

**ALTO:**
- Decisão desfavorável ao Tomador em impugnação à execução que discute o débito, com prazo para interposição de recurso
- Descumprimento, pelo Tomador, do acordo para parcelamento da dívida garantida pela apólice

**ALTÍSSIMO:**
- Decisão desfavorável ao Tomador em impugnação à execução que discute o débito, sem interposição de recurso
- Intimação do Tomador para pagamento da condenação
- Decisão determinando pagamento pela Seguradora
"""

# ══════════════════════════════════════════════════════════════════════════════
# REGRAS DE CALIBRAÇÃO — edite aqui para ajustar o comportamento da LLM
#
# Cada regra é uma instrução direta que a LLM segue ao classificar.
# Adicione, remova ou modifique regras conforme necessário.
# ══════════════════════════════════════════════════════════════════════════════

CALIBRATION_RULES = """
## REGRAS DE CALIBRAÇÃO

### PROGRESSÃO DOS EMBARGOS/IMPUGNAÇÃO (CRÍTICO — leia com atenção)
A classificação depende do ESTÁGIO atual dos embargos/impugnação, não apenas de existirem:

| Estágio dos Embargos/Impugnação | Risco |
|--------------------------------|-------|
| Opostos, ainda sem julgamento | Baixo |
| Julgados IMPROCEDENTES + recurso interposto com efeito suspensivo | Médio |
| Julgados IMPROCEDENTES + prazo para recurso em curso (sem recurso interposto ainda) | Alto |
| Julgados IMPROCEDENTES + resultado mantido em 2ª instância (sem trânsito em julgado) | Alto |
| Julgados IMPROCEDENTES + trânsito em julgado | Altíssimo |
| Julgados PROCEDENTES (tomador venceu a discussão do débito) | Baixo |

### AÇÃO ANULATÓRIA / MANDADO DE SEGURANÇA PARALELO
Quando a execução fiscal está suspensa aguardando ação anulatória ou MS:
- Sem decisão de 1ª instância na ação anulatória/MS = Baixo
- Sentença desfavorável ao Tomador na ação anulatória/MS + recurso de apelação pendente = Médio
- Sentença desfavorável mantida em 2ª instância (sem trânsito em julgado) = Alto
- Trânsito em julgado desfavorável na ação anulatória/MS = Altíssimo
- Sentença ou Acórdão FAVORÁVEL ao Tomador = Baixo

### TRÂNSITO EM JULGADO — VERIFICAR O MÉRITO (NÃO É AUTOMATICAMENTE ALTÍSSIMO)
"Trânsito em julgado" significa que não cabem mais recursos. Mas verifique O QUE transitou:
- Decisão DESFAVORÁVEL ao Tomador transitada em julgado = Altíssimo
- Decisão FAVORÁVEL ao Tomador transitada em julgado = Baixo
- Extinção sem resolução de mérito = Baixo (não houve condenação)
- Embargos PROCEDENTES transitados em julgado = Baixo (tomador venceu)

### RECUPERAÇÃO JUDICIAL (OBRIGATÓRIO)
Se "RECUPERAÇÃO JUDICIAL" ou "EM RJ" aparece no nome do Tomador:
- Agrave o risco em PELO MENOS um nível (Baixo→Médio, Médio→Alto, Alto→Altíssimo)
- NUNCA classifique como Baixo um Tomador em Recuperação Judicial, exceto se houve decisão favorável transitada em julgado

### PROCESSO BAIXADO/ARQUIVADO — DEPENDE DO MOTIVO
Processo baixado ou arquivado = Baixo SOMENTE se:
- O encerramento decorreu de decisão favorável ao Tomador, OU
- Não há condenação/débito pendente
Se o processo foi arquivado após trânsito em julgado DESFAVORÁVEL ao Tomador, manter o risco conforme a decisão (Alto ou Altíssimo).

### DECISÃO EM 2ª INSTÂNCIA + RECURSO ESPECIAL/EXTRAORDINÁRIO
Decisão desfavorável em 2ª instância com RE/REsp/Agravo pendente = ALTO (não Médio).
Recursos para tribunais superiores (STJ/STF/TST) NÃO têm efeito suspensivo automático.

### PARCELAMENTO/ACORDO
Acordo para parcelamento com manutenção da garantia = Médio.
Descumprimento do acordo pelo Tomador = Alto.

### REGRA DE DESEMPATE
Quando em dúvida entre dois níveis, escolha o MAIS ALTO — a seguradora prefere ser conservadora.

### RECOMENDAÇÕES
- Alto/Altíssimo: "Entrar em contato com o Tomador para avaliação de risco e possíveis providências"
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

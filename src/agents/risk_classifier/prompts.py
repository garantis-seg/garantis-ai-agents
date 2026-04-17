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
- Execução Fiscal suspensa em razão de acordo realizado entre Tomador e Segurado para parcelamento do débito, desde que seja definido pela manutenção da garantia na modalidade execução fiscal

**ALTO:**
- Decisão desfavorável ao Tomador em Embargos à Execução/Ação Anulatória que discute o débito sem a interposição de recurso pelo Tomador
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
- Apólice aceita no cumprimento de sentença/embargos à execução com julgamento procedente em favor do Tomador/Executado (êxito em relação à discussão integral do débito)
- Julgamento favorável ao Tomador em segunda ou última Instância

**MÉDIO:**
- Aceita a garantia no processo, julgamento desfavorável total ou parcialmente ao Tomador em 1ª Instância na execução/cumprimento de sentença com interposição de recurso de apelação e atribuição de efeito suspensivo
- Homologação de acordo para parcelamento do valor garantido na apólice com obrigatoriedade de manutenção da garantia

**ALTO:**
- Decisão desfavorável ao Tomador em Embargos à Execução/Cumprimento de Sentença que discute o débito com prazo para interposição de recurso
- Descumprimento, pelo Tomador, do acordo para parcelamento da dívida garantida pela apólice

**ALTÍSSIMO:**
- Decisão desfavorável ao Tomador em Embargos à Execução/Cumprimento de Sentença que discute o débito sem a interposição de recurso
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
- Aceita a garantia no processo, julgamento desfavorável ao Tomador em 1ª Instância na impugnação com interposição de recurso (agravo de petição) e atribuição de efeito suspensivo
- Homologação de acordo para parcelamento do valor garantido na apólice com obrigatoriedade de manutenção da garantia

**ALTO:**
- Decisão desfavorável ao Tomador em Impugnação à Execução que discute o débito com prazo para interposição de recurso
- Descumprimento, pelo Tomador, do acordo para parcelamento da dívida garantida pela apólice

**ALTÍSSIMO:**
- Decisão desfavorável ao Tomador em Impugnação à Execução que discute o débito sem a interposição de recurso
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

1. Decisão desfavorável em 2ª instância com recurso pendente (RE, REsp) = ALTO (não Médio)
2. Execução suspensa por embargos PENDENTES = BAIXO; embargos JULGADOS improcedentes = ALTO
3. Tomador em Recuperação Judicial agrava o risco em pelo menos um nível
4. **Quando em dúvida entre dois níveis, escolha o MAIS ALTO** — a seguradora prefere ser conservadora
5. Recomendações para Alto/Altíssimo: "Entrar em contato com o Tomador". Baixo/Médio: "Manter o acompanhamento"
6. **Processo BAIXADO/ARQUIVADO = Baixo**. Se o processo já foi encerrado (baixa definitiva, arquivamento), o risco de acionamento é Baixo independente do histórico, pois não há mais cobrança ativa. Mencione na justificativa que o processo está encerrado.
"""

# ══════════════════════════════════════════════════════════════════════════════
# EXEMPLOS DE REFERÊNCIA — few-shot examples para calibrar a LLM
#
# Formato: NÍVEL | Matéria: "Situação" → Recomendação: "Ação"
# Adicione exemplos reais (especialmente os que Poletto classificou)
# para melhorar a concordância.
# ══════════════════════════════════════════════════════════════════════════════

EXAMPLES = """
## EXEMPLOS DE CLASSIFICAÇÃO (referência)

ALTÍSSIMO | Tributário: "Apólice apresentada em Ação Anulatória com sentença desfavorável ao Tomador transitada em julgado." → Recomendação: "Entrar em contato com o Tomador e questionar como pagará o débito"
ALTO | Tributário: "Embargos julgados improcedentes com resultado desfavorável mantido em 2ª Instância, ainda não transitado em julgado." → Recomendação: "Entrar em contato com o Tomador a fim de verificar como pagará o débito"
ALTO | Cível: "Impugnação julgada improcedente com recursos sem efeito suspensivo." → Recomendação: "Entrar em contato com o Tomador"
ALTO | Trabalhista: "Acórdão desfavorável nos embargos à execução. Ação principal transitada em julgado, tomador ainda não intimado para pagamento." → Recomendação: "Verificar como pagará o débito"
MÉDIO | Tributário: "Embargos julgados improcedentes e prazo em curso para recorrer da sentença." → Recomendação: "Manter o acompanhamento"
BAIXO | Tributário: "Apólice aceita com embargos julgados procedentes. Execução fiscal suspensa." → Recomendação: "Manter o acompanhamento"
"""


def build_risk_prompt(processo_data: dict, movimentacoes: list[dict]) -> str:
    """Build the classification prompt with process data and movements.

    Args:
        processo_data: Dict with keys nr_processo, materia, fase, vl_is_total,
                       nm_tomador, rating_tomador, cnpj_tomador
        movimentacoes: List of movement dicts from Escavador API (data, tipo, conteudo)
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

    return f"""Você é um analista jurídico especializado em seguro garantia judicial, trabalhando para a seguradora Daycoval.
Sua tarefa é classificar o RISCO DE ACIONAMENTO de uma apólice de seguro garantia com base nos andamentos processuais mais recentes.

{RISK_MATRIX}

{EXAMPLES}

{CALIBRATION_RULES}

## INSTRUÇÕES

1. Leia atentamente as movimentações processuais abaixo
2. Identifique a MATÉRIA do processo (Fiscal, Cível ou Trabalhista)
3. Enquadre a situação atual do processo em UM dos critérios da matriz acima, correspondente à matéria correta
4. Classifique o risco como: Baixo, Medio, Alto ou Altissimo
5. Na justificativa, cite QUAL critério específico da matriz se aplica e por quê
6. Na recomendação, indique a ação prática que a equipe comercial/P&P deve tomar
7. No resumo de andamentos, liste os 3-5 eventos processuais mais relevantes em ordem cronológica

## DADOS DO PROCESSO

- Número: {processo_data.get('nr_processo', 'N/A')}
- Matéria: {processo_data.get('materia', 'N/A')}
- Fase: {processo_data.get('fase', 'N/A')}
- Importância Segurada (IS): {is_str}
- Tomador: {processo_data.get('nm_tomador', 'N/A')}
- Rating: {processo_data.get('rating_tomador', 'N/A')}

## MOVIMENTAÇÕES RECENTES (mais recentes primeiro)

{movs_text}

Responda EXCLUSIVAMENTE em JSON válido com os campos: risco, justificativa, recomendacao, andamentos_resumo."""

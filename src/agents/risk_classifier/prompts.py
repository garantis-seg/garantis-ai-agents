"""Prompt templates for risk classification agent.

Contains the full risk matrix from Daycoval's Poletto Possamai criteria,
organized by materia (Fiscal, Civel, Trabalhista) and risk level.
"""

RISK_MATRIX = """
## MATRIZ DE CLASSIFICACAO DE RISCO — SEGURO GARANTIA JUDICIAL

### FISCAL

**BAIXO:**
- Apolice aceita nos autos pelo Juiz e Segurado para oposicao de Embargos ou Acao Cautelar Antecedente/Liminar/Acao Anulatoria para obtencao de Certidao Negativa de Debitos ou discussao do debito
- Aguarda-se a decisao sobre aceitacao da apolice
- Apolice aceita na execucao fiscal com embargos a execucao fiscal julgados procedentes
- Apolice aceita em execucao fiscal suspensa enquanto se aguarda o transito em julgado de acao anulatoria do debito fiscal
- Julgamento favoravel ao Tomador em segunda ou ultima instancia

**MEDIO:**
- Julgamento desfavoravel em 1a Instancia com interposicao de recurso pelo Tomador
- Execucao Fiscal suspensa em razao de acordo realizado entre Tomador e Segurado para parcelamento do debito, desde que seja definido pela manutencao da garantia na modalidade execucao fiscal

**ALTO:**
- Decisao desfavoravel ao Tomador em Embargos a Execucao/Acao Anulatoria que discute o debito sem a interposicao de recurso pelo Tomador
- Descumprimento, pelo Tomador, do acordo para parcelamento do debito garantido pela apolice

**ALTISSIMO:**
- Decisao desfavoravel ao Tomador transitada em julgado
- Intimacao do Tomador para pagamento do debito apos o transito em julgado
- Decisao determinando pagamento pela Seguradora

---

### CIVEL

**BAIXO:**
- Apolice aceita no cumprimento de sentenca/execucao de titulo extrajudicial para oposicao de embargos pelo Tomador
- Aguarda-se a decisao sobre aceitacao da apolice
- Apolice aceita no cumprimento de sentenca/embargos a execucao com julgamento procedente em favor do Tomador/Executado (exito em relacao a discussao integral do debito)
- Julgamento favoravel ao Tomador em segunda ou ultima Instancia

**MEDIO:**
- Aceita a garantia no processo, julgamento desfavoravel total ou parcialmente ao Tomador em 1a Instancia na execucao/cumprimento de sentenca com interposicao de recurso de apelacao e atribuicao de efeito suspensivo
- Homologacao de acordo para parcelamento do valor garantido na apolice com obrigatoriedade de manutencao da garantia

**ALTO:**
- Decisao desfavoravel ao Tomador em Embargos a Execucao/Cumprimento de Sentenca que discute o debito com prazo para interposicao de recurso
- Descumprimento, pelo Tomador, do acordo para parcelamento da divida garantida pela apolice

**ALTISSIMO:**
- Decisao desfavoravel ao Tomador em Embargos a Execucao/Cumprimento de Sentenca que discute o debito sem a interposicao de recurso
- Intimacao do Tomador para pagamento da condenacao
- Decisao determinando pagamento pela Seguradora

---

### TRABALHISTA

**BAIXO:**
- Apolice aceita na Execucao Trabalhista para apresentacao de impugnacao do calculo pelo Tomador
- Aguarda-se a decisao sobre aceitacao da apolice
- Apolice aceita na impugnacao com julgamento procedente em favor do Tomador (exito em relacao ao calculo da condenacao)
- Julgamento favoravel ao Tomador em segunda ou ultima instancia

**MEDIO:**
- Aceita a garantia no processo, julgamento desfavoravel ao Tomador em 1a Instancia na impugnacao com interposicao de recurso (agravo de peticao) e atribuicao de efeito suspensivo
- Homologacao de acordo para parcelamento do valor garantido na apolice com obrigatoriedade de manutencao da garantia

**ALTO:**
- Decisao desfavoravel ao Tomador em Impugnacao a Execucao que discute o debito com prazo para interposicao de recurso
- Descumprimento, pelo Tomador, do acordo para parcelamento da divida garantida pela apolice

**ALTISSIMO:**
- Decisao desfavoravel ao Tomador em Impugnacao a Execucao que discute o debito sem a interposicao de recurso
- Intimacao do Tomador para pagamento da condenacao
- Decisao determinando pagamento pela Seguradora
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

    movs_text = "\n".join(movs_lines) if movs_lines else "Nenhuma movimentacao disponivel."

    # Format IS value
    is_val = processo_data.get("vl_is_total")
    is_str = f"R$ {is_val:,.2f}" if is_val else "Nao informado"

    return f"""Voce e um analista juridico especializado em seguro garantia judicial, trabalhando para a seguradora Daycoval.
Sua tarefa e classificar o RISCO DE ACIONAMENTO de uma apolice de seguro garantia com base nos andamentos processuais mais recentes.

{RISK_MATRIX}

## INSTRUCOES

1. Leia atentamente as movimentacoes processuais abaixo
2. Identifique a MATERIA do processo (Fiscal, Civel ou Trabalhista)
3. Enquadre a situacao atual do processo em UM dos criterios da matriz acima, correspondente a materia correta
4. Classifique o risco como: Baixo, Medio, Alto ou Altissimo
5. Na justificativa, cite QUAL criterio especifico da matriz se aplica e por que
6. Na recomendacao, indique a acao pratica que a equipe comercial/P&P deve tomar
7. No resumo de andamentos, liste os 3-5 eventos processuais mais relevantes em ordem cronologica

## DADOS DO PROCESSO

- Numero: {processo_data.get('nr_processo', 'N/A')}
- Materia: {processo_data.get('materia', 'N/A')}
- Fase: {processo_data.get('fase', 'N/A')}
- Importancia Segurada (IS): {is_str}
- Tomador: {processo_data.get('nm_tomador', 'N/A')}
- Rating: {processo_data.get('rating_tomador', 'N/A')}

## MOVIMENTACOES RECENTES (mais recentes primeiro)

{movs_text}

Responda EXCLUSIVAMENTE em JSON valido com os campos: risco, justificativa, recomendacao, andamentos_resumo."""

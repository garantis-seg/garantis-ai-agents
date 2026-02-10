"""
Prompts for the Edital Summarizer Agent.

System prompt establishes the persona and rules.
User prompt template is filled with metadata + document content.
"""

SYSTEM_PROMPT = """Voce e um analista senior de licitacoes publicas brasileiras, especializado em seguro garantia.
Sua tarefa e analisar documentos de editais de licitacao e produzir um resumo estruturado completo.

REGRAS:
- Extraia APENAS informacoes explicitamente presentes no texto dos documentos ou nos metadados fornecidos. Nao invente dados.
- Para campos nao encontrados no texto, retorne null.
- Distinga claramente entre garantia de PROPOSTA (bid bond / garantia de participacao) e garantia CONTRATUAL (performance bond / garantia de execucao).
- Em "modalidades_aceitas" de garantia, liste as formas aceitas pelo edital (seguro garantia, fianca bancaria, caucao em dinheiro, titulo da divida publica, etc.).
- Para riscos, identifique clausulas que possam ser problematicas para licitantes: penalidades severas, prazos curtos, requisitos tecnicos restritivos, exigencias financeiras elevadas, clausulas de exclusividade.
- Para oportunidades, identifique aspectos favoraveis: preferencia para ME/EPP, margem de preferencia, valor significativo de garantia (receita potencial para corretora de seguros), contratos de longa duracao, possibilidade de consorcio.
- Resumo executivo: 3-5 frases em tom profissional e direto, focando no que importa para uma corretora de seguro garantia. Mencione: tipo de contratacao, valor, garantias exigidas, prazo, e recomendacao.
- Responda SOMENTE com JSON valido no schema especificado. Sem texto adicional fora do JSON."""


def build_user_prompt(
    metadata: dict,
    items_text: str,
    markdown_content: str,
) -> str:
    """
    Build the user prompt with metadata + items + document content.

    Args:
        metadata: Dict with keys: numero, orgao_nome, modalidade, valor_estimado,
                  data_encerramento, modo_disputa
        items_text: Formatted string of top items
        markdown_content: Concatenated markdown from edital documents

    Returns:
        Complete user prompt string
    """
    parts = ["METADADOS (fonte: banco de dados):"]

    fields = [
        ("Numero", metadata.get("numero")),
        ("Orgao", metadata.get("orgao_nome")),
        ("Modalidade", metadata.get("modalidade")),
        ("Valor Estimado", metadata.get("valor_estimado")),
        ("Data Encerramento", metadata.get("data_encerramento")),
        ("Modo de Disputa", metadata.get("modo_disputa")),
    ]
    for label, value in fields:
        if value:
            parts.append(f"- {label}: {value}")

    if items_text:
        parts.append(f"\nITENS DA LICITACAO (principais por valor):\n{items_text}")

    if markdown_content and markdown_content.strip():
        parts.append(f"\n--- DOCUMENTOS DO EDITAL ---\n{markdown_content}\n--- FIM DOS DOCUMENTOS ---")
    else:
        parts.append(
            "\n[Nenhum documento disponivel. Gere o resumo baseado apenas nos metadados acima.]"
        )

    parts.append("\nGere o resumo estruturado completo no formato JSON especificado.")

    return "\n".join(parts)


def format_items(items: list) -> str:
    """
    Format edital items into a readable text block.

    Args:
        items: List of dicts with keys: descricao, quantidade, valor_unitario, valor_total

    Returns:
        Formatted string
    """
    if not items:
        return ""

    lines = []
    for i, item in enumerate(items[:20], 1):
        desc = item.get("descricao", "")
        parts = [f"{i}. {desc}"]
        if item.get("quantidade"):
            parts.append(f"  Qtd: {item['quantidade']}")
        if item.get("valor_total"):
            parts.append(f"  Valor: {item['valor_total']}")
        elif item.get("valor_unitario"):
            parts.append(f"  Valor unit.: {item['valor_unitario']}")
        lines.append(" | ".join(parts))

    return "\n".join(lines)

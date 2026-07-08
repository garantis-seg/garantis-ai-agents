"""
Prompts for Text Processor Agent.
"""

KEY_INFO_EXTRACTION_PROMPT = """Extraia as seguintes informações do texto abaixo.

Campos a extrair: {fields}

Contexto adicional: {context}

Para cada campo:
1. Busque o valor no texto
2. Se não encontrar, retorne null para o campo
3. Atribua uma confiança de 0 a 1

Retorne um objeto JSON com:
- extracted_fields: dicionário com os valores extraídos
- confidence: dicionário com a confiança de cada extração

TEXTO:
{text}"""


def build_extraction_prompt(
    text: str,
    fields: list[str],
    context: str | None = None
) -> str:
    """Build the key info extraction prompt."""
    return KEY_INFO_EXTRACTION_PROMPT.format(
        text=text,
        fields=", ".join(fields),
        context=context or "Documento genérico"
    )

"""
Prompts for Text Processor Agent.
"""

OCR_CORRECTION_PROMPT = """Você é um corretor de OCR especializado em {language}.

Corrija APENAS erros de OCR evidentes neste texto, mantendo:
- A estrutura original intacta (Markdown, formatação, etc.)
- Siglas técnicas e nomes próprios
- Números e valores exatos
- Formatação original (títulos, listas, etc.)

Tipos de correção permitidos:
- Caracteres trocados por OCR (l→I, 0→O, rn→m, etc.)
- Palavras quebradas incorretamente
- Espaçamento errado entre palavras
- Acentuação perdida no scan

NÃO corrija:
- Estilo de escrita ou gramática
- Termos técnicos legais
- Abreviações oficiais
- Conteúdo do texto (apenas erros de OCR)

Retorne APENAS o texto corrigido, sem explicações ou comentários.

TEXTO:
{text}"""


TEXT_FORMATTING_PROMPT = """Formate o texto abaixo para {target_format}.

Regras:
- Mantenha todo o conteúdo original
- Não adicione nem remova informação
- Apenas reorganize a estrutura conforme o formato solicitado

Formatos:
- markdown: Use headers (#), listas (-), negrito (**) quando apropriado
- plain: Texto simples sem formatação especial
- structured: Organize em seções claras com títulos

TEXTO:
{text}

Retorne APENAS o texto formatado."""


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


def build_ocr_correction_prompt(text: str, language: str = "português brasileiro") -> str:
    """Build the OCR correction prompt."""
    return OCR_CORRECTION_PROMPT.format(text=text, language=language)


def build_formatting_prompt(text: str, target_format: str = "markdown") -> str:
    """Build the text formatting prompt."""
    return TEXT_FORMATTING_PROMPT.format(text=text, target_format=target_format)


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

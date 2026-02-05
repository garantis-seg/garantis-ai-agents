"""
PDF OCR Agent prompts.
"""

PDF_TO_MARKDOWN_PROMPT = """Converta este documento PDF para Markdown de alta qualidade.

Regras:
- Preserve TODA a estrutura do documento (titulos, subtitulos, listas, tabelas)
- Use formatacao Markdown adequada (# para titulos, ## para subtitulos, - para listas, | para tabelas)
- Mantenha numeros, valores monetarios, datas, CPFs, CNPJs e siglas EXATAMENTE como aparecem
- Se houver tabelas, converta para formato Markdown table com alinhamento
- Preserve quebras de secao com --- (horizontal rule) entre secoes principais
- NAO adicione comentarios, explicacoes ou resumos - apenas o conteudo convertido
- Texto em portugues brasileiro - preserve acentuacao corretamente
- Se alguma parte estiver ilegivel, indique com [ilegivel]
- Preserve a hierarquia de titulos (H1 > H2 > H3)
- Listas numeradas devem manter a numeracao original

Retorne APENAS o texto Markdown, sem blocos de codigo e sem explicacoes."""

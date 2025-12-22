"""
Prompts for Edital Categorizer Agent.

Contains all prompt templates for L1/L2/L3 categorization and validation.
"""

from typing import List

# Common rules for categorization
L2_RULES = """
REGRAS PARA CATEGORIZAÇÃO L2:
- MESMO NÍVEL SEMÂNTICO: Todas as categorias L2 devem estar no mesmo nível de abstração
- SEM SOBREPOSIÇÃO: Categorias não devem se sobrepor semanticamente
- NOMENCLATURA PROFISSIONAL: Use termos técnicos do governo brasileiro
- PREFERIR EXISTENTES: Escolha categoria existente se apropriada (confiança > 0.7)
- NOVA APENAS SE NECESSÁRIO: Crie nova categoria apenas se nenhuma existente servir (is_new=true, id=-1)
- IGNORE LOCALIZAÇÃO: Ignore aspectos específicos de localização geográfica
- NOMES CURTOS: Máximo 20 caracteres ideal
"""

L3_RULES = """
REGRAS PARA CATEGORIZAÇÃO L3:
- DEVE SER SUBCONJUNTO: L3 deve ser especialização clara da categoria L2
- MESMO NÍVEL: Todas L3 no mesmo nível de detalhamento
- SEM SOBREPOSIÇÃO: Subcategorias distintas entre si
- ESPECÍFICO MAS NÃO EXCESSIVO: Útil para filtragem
- IGNORE LOCALIZAÇÃO: Ignore aspectos específicos de localização
- SEM REDUNDÂNCIA: NÃO repita palavras da categoria L2
- NOMES CURTOS: Máximo 20 caracteres ideal
"""


def build_l1_prompt(context: str) -> str:
    """Build prompt for L1 (serviço/produto) categorization."""
    return f"""Analise o seguinte edital de licitação e determine se é um "serviço" ou "produto".

EDITAL:
{context}

CATEGORIAS L1 DISPONÍVEIS:
- Serviços [1] - Prestação de atividades, mão de obra, consultorias, manutenções, limpeza, segurança, etc.
- Produtos [2] - Aquisição/fornecimento de bens materiais, equipamentos, medicamentos, móveis, etc.

CRITÉRIOS DE DECISÃO:
- SERVIÇOS: Quando o objeto principal é a prestação de uma atividade ou trabalho
- PRODUTOS: Quando o objeto principal é a aquisição de bens físicos ou materiais

Responda APENAS com JSON válido no formato:
{{"id": 1, "name": "serviço", "confidence": 0.95}}

ou

{{"id": 2, "name": "produto", "confidence": 0.95}}
"""


def build_l2_prompt(context: str, base_type: str, existing_categories: List[str]) -> str:
    """Build prompt for L2 categorization."""
    categories_text = "\n".join([f"- {cat}" for cat in existing_categories]) if existing_categories else "- Outros [999]"

    return f"""Categorize este edital em uma das categorias L2 existentes ou sugira uma nova.

EDITAL:
{context}

TIPO BASE: {base_type}

CATEGORIAS L2 DISPONÍVEIS PARA {base_type.upper()}:
{categories_text}

{L2_RULES}

FORMATO DO ID:
- O número entre colchetes [] é o ID da categoria
- Use esse ID no campo "id" da resposta
- Se sugerir nova categoria: use id=-1 e is_new=true

Responda APENAS com JSON válido:
{{"id": 123, "name": "Nome da Categoria", "confidence": 0.85, "is_new": false}}

Para nova categoria:
{{"id": -1, "name": "Nova Categoria Sugerida", "confidence": 0.75, "is_new": true}}
"""


def build_l3_prompt(context: str, l2_category: str, existing_categories: List[str]) -> str:
    """Build prompt for L3 categorization."""
    categories_text = "\n".join([f"- {cat}" for cat in existing_categories]) if existing_categories else "- Outros [999]"

    return f"""Categorize este edital em uma subcategoria L3 da categoria L2 "{l2_category}".

EDITAL:
{context}

CATEGORIA L2: {l2_category}

SUBCATEGORIAS L3 DISPONÍVEIS:
{categories_text}

{L3_RULES}

IMPORTANTE: A L3 NÃO deve repetir palavras da L2 "{l2_category}"

FORMATO DO ID:
- O número entre colchetes [] é o ID da subcategoria
- Use esse ID no campo "id" da resposta
- Se sugerir nova subcategoria: use id=-1 e is_new=true

Responda APENAS com JSON válido:
{{"id": 456, "name": "Nome da Subcategoria", "confidence": 0.85, "is_new": false}}

Para nova subcategoria:
{{"id": -1, "name": "Nova Subcategoria", "confidence": 0.75, "is_new": true}}
"""


def build_validation_prompt(
    context: str,
    base_type: str,
    l2_category: str,
    l3_category: str,
    existing_l2: List[str],
    existing_l3: List[str],
) -> str:
    """Build prompt for L2/L3 validation."""
    l2_list = ", ".join(existing_l2[:20]) if existing_l2 else "Nenhuma"
    l3_list = ", ".join(existing_l3[:15]) if existing_l3 else "Nenhuma"

    return f"""Você é um validador sênior especialista em categorização de licitações do governo brasileiro.

EDITAL PARA VALIDAÇÃO:
Tipo Base: {base_type}
Contexto: {context[:800]}

CATEGORIZAÇÃO PROPOSTA:
L2: "{l2_category}"
L3: "{l3_category}"

CATEGORIAS DISPONÍVEIS:
L2 existentes para {base_type}: {l2_list}...
L3 existentes para "{l2_category}": {l3_list}...

CRITÉRIOS DE VALIDAÇÃO:

✅ L2 ADEQUADO:
- Específico e profissional para {base_type}
- Não genérico demais ou específico demais
- Consistente com padrões existentes
- Máximo 20 chars ideal

✅ L3 ADEQUADO:
- Subcategoria clara de "{l2_category}"
- JAMAIS repete palavras da L2 (CRÍTICO!)
- Mesmo nível de granularidade das L3 existentes
- Útil para filtragem
- Máximo 20 chars ideal

EXEMPLOS PROIBIDOS para L2="{l2_category}":
- L3 contendo palavras de "{l2_category}"
- Qualquer repetição de termos da L2

TAREFA:
1. Se a categorização está CORRETA → approved: true
2. Se precisa CORREÇÃO → approved: false, forneça suggested_l2 e/ou suggested_l3

Responda APENAS com JSON válido:
{{"approved": true, "suggested_l2": null, "suggested_l3": null}}

ou

{{"approved": false, "suggested_l2": "Categoria Correta", "suggested_l3": "Subcategoria Correta"}}
"""


def build_title_optimization_prompt(
    edital_data: dict,
    l1_type: str,
    l2_category: str,
    l3_category: str,
) -> str:
    """Build prompt for title optimization."""
    original_title = edital_data.get("title", "")
    description = edital_data.get("description", "")
    orgao_nome = edital_data.get("orgao_nome", "")
    modalidade = edital_data.get("modalidade_licitacao_nome", "")
    objeto_compra = edital_data.get("objeto_compra", "")
    top_items = edital_data.get("top_items", [])

    items_context = ""
    if top_items:
        items_context = f"\n- Principais itens: {', '.join(top_items[:3])}"

    return f"""TAREFA: OTIMIZAÇÃO DE TÍTULO DE EDITAL

CONTEXTO DO EDITAL:
- Título Original: {original_title}
- Órgão: {orgao_nome}
- Modalidade: {modalidade}
- Tipo Base: {l1_type}
- Categoria L2: {l2_category}
- Categoria L3: {l3_category}
- Objeto da Compra: {objeto_compra}{items_context}
- Descrição: {description[:200]}

REGRAS DE PADRONIZAÇÃO:
✅ TAMANHO: Idealmente até 40 caracteres, máximo absoluto 60 caracteres
✅ REMOVER: Nome do órgão, cidade, estado, localização específica
✅ FOCAR: Essência do que está sendo contratado/adquirido
✅ ESTRUTURA: [Objeto Principal] + [Especificação Técnica se necessária]
✅ LINGUAGEM: Concisa, profissional, técnica
✅ EVITAR: Redundância com categorias L2/L3

PADRÕES DE QUALIDADE:
- Para SERVIÇOS: Evitar "Serviços de [x]". Preferir: "[Tipo de serviço]"
- Para PRODUTOS: Evitar "Aquisição de [x]". Preferir: "[Tipo de produto]"
- Usar as categorias L2/L3 como referência de terminologia

EXEMPLOS:
❌ "Contratação de empresa terceirizada para prestação de serviços de limpeza na Secretaria de São Paulo"
✅ "Limpeza e conservação predial" (34 chars)

❌ "Aquisição de equipamentos de informática completos com monitor, teclado e mouse"
✅ "Computadores desktop completos" (29 chars)

Responda APENAS com JSON válido:
{{"optimized_title": "título otimizado de até 60 caracteres"}}
"""

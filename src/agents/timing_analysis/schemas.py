"""
Pydantic schemas para o agente de timing analysis.
Port de poc-prompt-benchmark/src/lib/types.ts para Python.
"""

from enum import Enum
from typing import Literal, Optional
from pydantic import BaseModel, Field


# ========== Enums ==========

class TimingBase(str, Enum):
    """Classificação base de timing."""
    AGORA_CONSTITUICAO = "AGORA_CONSTITUICAO"
    AGORA_SUBSTITUICAO = "AGORA_SUBSTITUICAO"
    ACOMPANHAR = "ACOMPANHAR"
    PASSOU = "PASSOU"


class TipoGarantia(str, Enum):
    """Tipos de garantia existente."""
    DEPOSITO_JUDICIAL = "deposito_judicial"
    PENHORA_DINHEIRO = "penhora_dinheiro"
    PENHORA_BENS_MOVEIS = "penhora_bens_moveis"
    PENHORA_BENS_IMOVEIS = "penhora_bens_imoveis"
    FIANCA_BANCARIA = "fianca_bancaria"
    SEGURO_GARANTIA = "seguro_garantia"
    HIPOTECA_JUDICIAL = "hipoteca_judicial"
    CAUCAO_REAL = "caucao_real"
    INDEFINIDO = "indefinido"
    OUTRO = "outro"


class GarantiaAnswer(str, Enum):
    """Resposta sobre existência de garantia (escala 5 níveis)."""
    SIM = "SIM"
    PROVAVELMENTE_SIM = "PROVAVELMENTE_SIM"
    INCERTO = "INCERTO"
    PROVAVELMENTE_NAO = "PROVAVELMENTE_NAO"
    NAO = "NÃO"


class InferenceBasis(str, Enum):
    """Base da inferência sobre garantia."""
    DIRETA = "direta"
    SILENCIO = "silencio"
    AUSENCIA_CONFIRMADA = "ausencia_confirmada"


class AtividadePosMarco(str, Enum):
    """Tipo de atividade após o marco temporal."""
    ROTINEIRA = "rotineira"
    CONSTRITIVA = "constritiva"
    SILENCIO = "silencio"


# ========== Nó 1 - Plausibilidade ==========

class Node1Plausibilidade(BaseModel):
    """Nó 1: A natureza da ação comporta garantia?"""
    answer: Literal["SIM", "NÃO"] = Field(
        description="SIM se a natureza da ação comporta garantia, NÃO caso contrário"
    )
    reasoning: str = Field(
        description="Breve análise da natureza da ação e se o rito comporta garantia"
    )


# ========== Nó 2 - Materialização ==========

class Node2Materializacao(BaseModel):
    """Nó 2: A necessidade de garantia se materializou?"""
    answer: Literal["SIM", "NÃO"] = Field(
        description="SIM se a necessidade se tornou prática, NÃO caso contrário"
    )
    reasoning: str = Field(
        description="Descrição dos indícios de que a necessidade se tornou prática"
    )


# ========== Nó 3 - Marcos Temporais ==========

class Marco(BaseModel):
    """Marco temporal básico."""
    data: str = Field(description="Data no formato DD/MM/YYYY")
    evento: str = Field(description="Tipo do evento (Citação, Distribuição, etc)")
    descricao: Optional[str] = Field(
        default=None,
        description="Explicação do nascimento da necessidade"
    )


class MarcoMaisRecente(BaseModel):
    """Marco mais recente com campos adicionais."""
    data: str = Field(description="Data no formato DD/MM/YYYY")
    evento: str = Field(description="Descrição do evento")
    e_mesmo_que_primario: bool = Field(
        description="True se este marco é o mesmo que o primário"
    )
    relevancia: Optional[str] = Field(
        default=None,
        description="Por que este marco reforça a necessidade (preencher apenas se diferente do primário)"
    )


class MarcoRenovacao(BaseModel):
    """Marco de renovação (fato novo que reabriu janela)."""
    data: str = Field(description="Data no formato DD/MM/YYYY")
    evento: str = Field(description="Descrição do fato novo")
    descricao: str = Field(description="Por que este fato reabriu a janela de oportunidade")


class ContextoEspecial(BaseModel):
    """Detecção de contexto especial."""
    detected: bool = Field(description="True se o contexto foi detectado")
    evidence: Optional[str] = Field(
        default=None,
        description="Trecho exato da movimentação que evidencia o contexto"
    )


class ContextosEspeciais(BaseModel):
    """Todos os contextos especiais detectáveis."""
    processo_suspenso: ContextoEspecial
    recuperacao_judicial: ContextoEspecial
    acordo_em_negociacao: ContextoEspecial
    fase_recursal: ContextoEspecial
    multiplos_reus: ContextoEspecial
    falencia_devedor: ContextoEspecial


class Node3MarcosTemporais(BaseModel):
    """Nó 3: Identificação dos marcos temporais."""
    marco_primario: Marco = Field(
        description="Primeiro ato que tornou a garantia juridicamente plausível"
    )
    marco_mais_recente: MarcoMaisRecente = Field(
        description="Ato mais recente que reforça a necessidade"
    )
    marco_renovacao: Optional[MarcoRenovacao] = Field(
        default=None,
        description="Fato novo que reabriu a janela de oportunidade"
    )
    atividade_pos_marco: AtividadePosMarco = Field(
        description="Natureza da movimentação após o marco mais recente"
    )
    contextos_especiais: ContextosEspeciais = Field(
        description="Contextos especiais detectados"
    )
    resumo: str = Field(
        description="Resumo narrativo da linha do tempo e situação atual"
    )


# ========== Nó 4 - Garantia Existente ==========

class Node4GarantiaExistente(BaseModel):
    """Nó 4: Status da garantia existente."""
    answer: GarantiaAnswer = Field(
        description="Classificação da existência de garantia (5 níveis)"
    )
    inference_basis: InferenceBasis = Field(
        description="Base da inferência: direta, silêncio ou ausência_confirmada"
    )
    reasoning: str = Field(
        description="Identificação de ativos onerados, apólices ou depósitos — ou inferência"
    )


# ========== Nó 5A - Substituição ==========

class Details5A(BaseModel):
    """Detalhes para caminho 5A (substituição de garantia existente)."""
    tipo_garantia: TipoGarantia = Field(
        description="Tipo de garantia existente"
    )
    tipo_garantia_detalhe: Optional[str] = Field(
        default=None,
        description="Detalhe adicional se tipo_garantia = 'outro'"
    )
    data_oferecimento_garantia: Optional[str] = Field(
        default=None,
        description="Data de oferecimento da garantia no formato DD/MM/YYYY"
    )
    garantia_onerosa: bool = Field(
        description="True se a garantia atual onera o fluxo de caixa ou imobiliza ativos"
    )
    is_candidate: Literal["SIM", "NÃO"] = Field(
        description="SIM se é candidato a substituição por seguro garantia"
    )
    reasoning: str = Field(
        description="Análise sobre potencial de substituição"
    )


# ========== Nó 5B - Constituição ==========

class Details5B(BaseModel):
    """Detalhes para caminho 5B (constituição de nova garantia)."""
    ameaca_constricao_iminente: bool = Field(
        description="True se há despacho/decisão indicando constrição ordenada mas não efetivada"
    )
    executado_ativo: bool = Field(
        description="True se o executado demonstrou iniciativa de defesa"
    )
    processo_encerrado: bool = Field(
        description="True se o processo está encerrado, arquivado ou extinto"
    )
    is_candidate: Literal["SIM", "NÃO"] = Field(
        description="SIM se é candidato a constituição de garantia"
    )
    reasoning: str = Field(
        description="Análise sobre oportunidade de constituição de garantia"
    )


# ========== Nó 5 - Análise Específica ==========

class Node5AnaliseEspecifica(BaseModel):
    """Nó 5: Análise específica (5A ou 5B)."""
    type_active: Literal["5A_SUBSTITUICAO", "5B_CONSTITUICAO"] = Field(
        description="Caminho ativo: 5A para substituição, 5B para constituição"
    )
    details_5a: Optional[Details5A] = Field(
        default=None,
        description="Detalhes do caminho 5A (preencher apenas se type_active = 5A_SUBSTITUICAO)"
    )
    details_5b: Optional[Details5B] = Field(
        default=None,
        description="Detalhes do caminho 5B (preencher apenas se type_active = 5B_CONSTITUICAO)"
    )


# ========== Variáveis LLM ==========

class VariaveisLLM(BaseModel):
    """Variáveis auxiliares extraídas pelo LLM."""
    garantia_inferida_silencio: bool = Field(
        default=False,
        description="True se a garantia foi inferida por silêncio (não confirmada diretamente)"
    )
    tipo_garantia_desconhecido: bool = Field(
        default=False,
        description="True se o tipo de garantia não pôde ser identificado"
    )
    evidencia_direta_garantia_onerosa: bool = Field(
        default=False,
        description="True se há evidência direta de que a garantia é onerosa"
    )
    executado_demonstrou_passividade: bool = Field(
        default=False,
        description="True se o executado demonstrou passividade histórica"
    )


# ========== Resposta Completa do LLM ==========

class LLMResponseV3(BaseModel):
    """
    Resposta completa do LLM (V3) - 5 nodes decision tree.

    Esta é a estrutura que o ADK output_schema vai forçar o LLM a retornar.
    Nodes 2-5 são opcionais (null se Node 1 = NÃO ou saída antecipada).
    """
    node_1_plausibilidade: Node1Plausibilidade
    node_2_materializacao: Optional[Node2Materializacao] = None
    node_3_marcos_temporais: Optional[Node3MarcosTemporais] = None
    node_4_garantia_existente: Optional[Node4GarantiaExistente] = None
    node_5_analise_especifica: Optional[Node5AnaliseEspecifica] = None
    variaveis_llm: VariaveisLLM

    class Config:
        use_enum_values = True

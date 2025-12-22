"""
Request schemas para a API.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class CaseData(BaseModel):
    """Dados do processo."""
    processo_numero: str = Field(description="Número do processo")
    foro: Optional[str] = Field(default=None, description="Tribunal/Foro")
    classe: Optional[str] = Field(default=None, description="Classe processual")
    assunto: Optional[str] = Field(default=None, description="Assunto")
    case_value: Optional[float] = Field(default=None, description="Valor da ação")
    polo_ativo: Optional[Any] = Field(default=None, description="Polo ativo (exequente/autor)")
    polo_passivo: Optional[Any] = Field(default=None, description="Polo passivo (executado/réu)")
    executado_advogado: Optional[str] = Field(default=None, description="Advogado do executado")
    exequente_advogado_nome: Optional[str] = Field(default=None, description="Advogado do exequente")


class Movement(BaseModel):
    """Movimentação processual."""
    data_movimento: str = Field(description="Data da movimentação")
    descricao: str = Field(description="Descrição da movimentação")


class AnalyzeRequest(BaseModel):
    """Request para análise de timing."""
    case_data: CaseData = Field(description="Dados do processo")
    movements: List[Movement] = Field(default=[], description="Lista de movimentações")
    model: Optional[str] = Field(default=None, description="Modelo a usar (default: gemini-2.0-flash)")
    prompt_version: Optional[str] = Field(default=None, description="Versão do prompt (default: v3)")
    force_refresh: bool = Field(default=False, description="Forçar nova análise mesmo se cacheada")


class AnalyzeBatchRequest(BaseModel):
    """Request para análise em lote."""
    items: List[AnalyzeRequest] = Field(description="Lista de processos para analisar")
    model: Optional[str] = Field(default=None, description="Modelo a usar para todos")
    prompt_version: Optional[str] = Field(default=None, description="Versão do prompt para todos")

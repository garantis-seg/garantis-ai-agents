"""
Funções para cálculos temporais.
"""

from datetime import date, datetime
from typing import Optional

from ..agents.timing_analysis.schemas import LLMResponseV3
from .types import CalculatedTemporalData


def parse_date(date_str: str) -> Optional[date]:
    """
    Converte data DD/MM/YYYY para objeto date.

    Args:
        date_str: Data no formato DD/MM/YYYY

    Returns:
        Objeto date ou None se inválido.
    """
    if not date_str:
        return None

    try:
        parts = date_str.split("/")
        if len(parts) != 3:
            return None

        day, month, year = map(int, parts)
        return date(year, month, day)
    except (ValueError, TypeError):
        return None


def diff_in_days(date1: date, date2: date) -> int:
    """
    Calcula diferença em dias entre duas datas.

    Args:
        date1: Data mais recente
        date2: Data mais antiga

    Returns:
        Número de dias de diferença.
    """
    return (date1 - date2).days


def calculate_temporal_data(
    response: LLMResponseV3,
    today: Optional[date] = None,
) -> Optional[CalculatedTemporalData]:
    """
    Calcula dados temporais a partir dos marcos.

    Args:
        response: Resposta do LLM (V3)
        today: Data de referência (default: hoje)

    Returns:
        Dados temporais calculados ou None se não houver marcos.
    """
    today = today or date.today()

    marcos = response.node_3_marcos_temporais
    if not marcos:
        return None

    marco_primario_date = parse_date(marcos.marco_primario.data)
    marco_mais_recente_date = parse_date(marcos.marco_mais_recente.data)

    if not marco_primario_date or not marco_mais_recente_date:
        return None

    return CalculatedTemporalData(
        dias_desde_marco_primario=diff_in_days(today, marco_primario_date),
        dias_desde_marco_mais_recente=diff_in_days(today, marco_mais_recente_date),
    )

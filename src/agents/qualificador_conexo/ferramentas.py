"""Ferramentas do qualificador: menu fechado, budget e circuit breaker.

O circuit breaker é o MESMO do Investigador do C4
(`calculo_ficha.ferramentas.CircuitBreaker`): 3 falhas seguidas de
(ferramenta, documento) tiram a ferramenta do menu daquele documento.

O budget é próprio, porque a S2c conta por ITEM (processo ou garantia), e o C4
conta por célula. Decisão de 22/10/2026 (pedido do Alfredo):

- 30 chamadas de ferramenta por conexo.
- 5 chamadas por item.
- 3 páginas cruas por documento (o mesmo teto do C4).

Budget esgotado encerra a leitura. O agente emite a resposta com o que leu, e as
regras duras do código continuam a valer. Assim, o budget nunca vira resposta sem
prova: um `e_fiscal=false` ou uma garantia `liberada` sem prova voltam como erro.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Optional

from ..calculo_ficha.ferramentas import FALHAS_PARA_ABRIR, CircuitBreaker

#: O menu FECHADO. A ordem é a do fluxo natural: resumir → perguntar → página.
FERRAMENTAS: tuple[str, ...] = (
    "resumir_com_missao",
    "perguntar_ao_documento",
    "pedir_pagina",
)


@dataclass
class BudgetConexo:
    max_por_conexo: int = 30
    max_por_item: int = 5
    max_paginas_por_doc: int = 3

    chamadas: int = 0
    por_item: dict[str, int] = field(default_factory=dict)

    def esgotado(self) -> bool:
        return self.chamadas >= self.max_por_conexo

    def item_esgotado(self, item: str) -> bool:
        return self.por_item.get(item, 0) >= self.max_por_item

    def restante(self) -> int:
        return max(0, self.max_por_conexo - self.chamadas)


_BLOCO_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_chamada(texto: str) -> Optional[dict]:
    """A chamada do turno de decisão, ou None.

    Aceita JSON puro, JSON em fence ou JSON no meio de texto. Formas válidas:
    `{"tool": "<nome do menu>", "args": {...}}` ou `{"fim": true}`.
    """
    if not texto:
        return None
    m = _BLOCO_JSON_RE.search(texto)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except (ValueError, TypeError):
        return None
    if not isinstance(obj, dict):
        return None
    if obj.get("fim") is True:
        return {"fim": True}
    tool = obj.get("tool")
    if isinstance(tool, str) and tool in FERRAMENTAS:
        args = obj.get("args")
        return {"tool": tool, "args": dict(args) if isinstance(args, dict) else {}}
    return None


def menu(breaker: CircuitBreaker) -> list[str]:
    """O menu da rodada, com os circuitos abertos nomeados."""
    fechados = [f"fechada: {t} no documento {d}" for (t, d) in sorted(breaker.abertas)]
    return list(FERRAMENTAS) + fechados


__all__ = [
    "FALHAS_PARA_ABRIR",
    "FERRAMENTAS",
    "BudgetConexo",
    "CircuitBreaker",
    "menu",
    "parse_chamada",
]

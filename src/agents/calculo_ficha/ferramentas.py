"""Ferramentas do INVESTIGADOR — menu fechado, budget e circuit breaker.

DESENHO-INVESTIGADOR §2.2/§8.6. Quatro ferramentas e nenhuma a mais (acima de
15-20 a selecao degrada; e `buscar_no_documento` deliberadamente NAO existe
nesta onda). O protocolo de chamada e TEXTO TOLERANTE (§6.1): a supressao de
tool-calling medida na pesquisa vem do response_schema no turno de decisao,
nao da ausencia de tools nativas — entao o turno de decisao roda SEM schema e
o parser aceita o JSON da chamada onde ele estiver.

O teto de 40 tool calls e deliberadamente BAIXO: a acuracia factual cai ~42%
de 2 para 150 calls com as metricas de superficie estaveis (arXiv:2605.06635).
Estouro de budget NUNCA vira numero apressado — vira `indefinido` la no
harness, via success=false com motivo `budget`.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

#: O menu FECHADO. A ordem e a do fluxo natural: resumir → perguntar →
#: (escape hatch) pagina → submeter.
FERRAMENTAS: tuple[str, ...] = (
    "resumir_com_missao",
    "perguntar_ao_documento",
    "pedir_pagina",
    "submeter_celulas",
)

#: Falhas CONSECUTIVAS da mesma ferramenta no mesmo documento ate ela sumir
#: do menu daquele doc (§3.4 / pesquisa §6.6: o modo de falha nº1 e o agente
#: repetindo a mesma chamada que falha).
FALHAS_PARA_ABRIR = 3


@dataclass
class Budget:
    """§8.6 — os tetos por ficha. Baixos de proposito."""

    max_tool_calls_por_ficha: int = 40
    max_tool_calls_por_celula: int = 6
    max_usd_por_ficha: float = 2.00
    max_paginas_por_doc: int = 3
    max_leitores_paralelos: int = 4

    tool_calls: int = 0
    custo_usd: float = 0.0

    def estourado(self) -> Optional[str]:
        if self.tool_calls >= self.max_tool_calls_por_ficha:
            return f"budget de {self.max_tool_calls_por_ficha} tool calls esgotado"
        if self.custo_usd >= self.max_usd_por_ficha:
            return f"budget de US$ {self.max_usd_por_ficha:.2f} esgotado"
        return None


@dataclass
class CircuitBreaker:
    """3 falhas consecutivas de (ferramenta, doc) → ela some do menu DAQUELE
    doc, com nota na memoria do loop. Sucesso zera a contagem."""

    falhas: dict = field(default_factory=dict)   # (tool, doc_id) -> consecutivas
    abertas: set = field(default_factory=set)    # (tool, doc_id) fora do menu

    def registrar_falha(self, tool: str, doc_id: str) -> bool:
        """Devolve True se o circuito ABRIU agora."""
        chave = (tool, doc_id or "")
        n = self.falhas.get(chave, 0) + 1
        self.falhas[chave] = n
        if n >= FALHAS_PARA_ABRIR and chave not in self.abertas:
            self.abertas.add(chave)
            logger.warning("INVESTIGADOR_BREAKER_ABERTO tool=%s doc=%s", tool, doc_id)
            return True
        return False

    def registrar_sucesso(self, tool: str, doc_id: str) -> None:
        self.falhas.pop((tool, doc_id or ""), None)

    def disponivel(self, tool: str, doc_id: str) -> bool:
        return (tool, doc_id or "") not in self.abertas

    def indisponiveis_do_doc(self, doc_id: str) -> list[str]:
        return sorted(t for (t, d) in self.abertas if d == (doc_id or ""))


# ── protocolo de chamada em texto tolerante ─────────────────────────────────

_BLOCO_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_chamada(texto: str) -> Optional[dict]:
    """Extrai a chamada de ferramenta do turno de decisao.

    Aceita: JSON puro, JSON em fence, JSON no meio de prosa. Formas validas:
    `{"tool": "<nome>", "args": {...}}` ou `{"fim": true}`. Qualquer outra
    coisa devolve None — o loop trata como falha de protocolo (com retry),
    nunca como resposta.
    """
    if not texto:
        return None
    m = _BLOCO_JSON_RE.search(texto)
    if not m:
        return None
    bruto = m.group(0)
    # fence dentro do bloco atrapalha? tenta do maior pro menor recorte
    for candidato in (bruto, bruto[bruto.find("{"): bruto.rfind("}") + 1]):
        try:
            obj = json.loads(candidato)
        except (ValueError, TypeError):
            continue
        if not isinstance(obj, dict):
            continue
        if obj.get("fim") is True:
            return {"fim": True}
        tool = obj.get("tool")
        if isinstance(tool, str) and tool in FERRAMENTAS:
            args = obj.get("args")
            return {"tool": tool, "args": dict(args) if isinstance(args, dict) else {}}
    return None


def menu_do_investigador(
    doc_ids: list[str], breaker: CircuitBreaker
) -> list[dict[str, Any]]:
    """O menu efetivo desta rodada de decisao — ja sem os circuitos abertos."""
    fora = {t for d in doc_ids for t in breaker.indisponiveis_do_doc(d)}
    menu = []
    for nome in FERRAMENTAS:
        if nome == "submeter_celulas" or nome not in fora:
            menu.append({"tool": nome})
    return menu


__all__ = [
    "FERRAMENTAS",
    "FALHAS_PARA_ABRIR",
    "Budget",
    "CircuitBreaker",
    "parse_chamada",
    "menu_do_investigador",
]

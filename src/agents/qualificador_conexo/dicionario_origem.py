"""Dicionário FECHADO da origem do caso (`estado_processual.origem.tipo`).

Decisão do Alfredo, 03/11/2026: "Precisa ser o gemini; mas ele tem que ter um
guidance. e dicionario fechado." O Gemini lê os documentos. O código aceita
`origem.tipo` só quando o trecho literal da prova tem uma expressão deste
dicionário, e a expressão é do mesmo tipo.

Por quê: com a mesma entrada, o agente respondeu `auto_de_infracao` numa rodada
e null na outra. O `origem.tipo` escolhe a 1ª caixa da timeline da ficha. Um
dicionário fechado torna a resposta conferível pelo código.

Este módulo é o DONO ÚNICO do dicionário. O prompt (`prompts.py`) e a regra
dura (`agent.py`) leem `EXPRESSOES_ORIGEM` e as funções daqui. Não redigite as
expressões em outro arquivo.

Funções puras. Sem rede e sem LLM.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional

#: Cada tipo de origem e as expressões que o provam. A lista é FECHADA: uma
#: expressão nova entra só por PR, com teste.
EXPRESSOES_ORIGEM: dict[str, tuple[str, ...]] = {
    "auto_de_infracao": (
        "auto de infração",
        "lançamento de ofício",
        "notificação de lançamento",
        "auto de lançamento",
        "impugnação",
    ),
    "despacho_decisorio": (
        "despacho decisório",
        "PER/DCOMP",
        "pedido de restituição",
        "pedido de ressarcimento",
        "declaração de compensação",
        "compensação não homologada",
        "manifestação de inconformidade",
    ),
    "aiim": (
        "AIIM",
        "auto de infração e imposição de multa",
    ),
}

#: A defesa de 1ª instância de cada trilho federal. Ela desempata quando o
#: trecho tem expressões dos 2 grupos federais.
DEFESA_DE_1A_INSTANCIA: dict[str, str] = {
    "auto_de_infracao": "impugnação",
    "despacho_decisorio": "manifestação de inconformidade",
}

_FEDERAIS = frozenset(DEFESA_DE_1A_INSTANCIA)


def normalizar(texto: str) -> str:
    """Caixa baixa, sem acento e com um só espaço entre as palavras."""
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c)
    )
    return re.sub(r"\s+", " ", sem_acento.casefold()).strip()


def _padrao(expressao: str) -> re.Pattern[str]:
    # A borda de palavra impede que "aiim" case dentro de outra palavra.
    return re.compile(r"(?<!\w)" + re.escape(normalizar(expressao)) + r"(?!\w)")


def expressoes_no_trecho(trecho: str) -> dict[str, list[str]]:
    """As expressões do dicionário que o trecho tem, por tipo.

    A expressão mais longa vence a mais curta no mesmo lugar do texto. Assim,
    "auto de infração e imposição de multa" conta só para `aiim`, e não também
    para `auto_de_infracao`.
    """
    texto = normalizar(trecho or "")
    pares = sorted(
        ((tipo, exp) for tipo, exps in EXPRESSOES_ORIGEM.items() for exp in exps),
        key=lambda par: len(normalizar(par[1])), reverse=True,
    )
    achadas: dict[str, list[str]] = {}
    for tipo, exp in pares:
        padrao = _padrao(exp)
        if padrao.search(texto):
            achadas.setdefault(tipo, []).append(exp)
            # Apaga o trecho casado. Uma expressão mais curta não casa de novo nele.
            texto = padrao.sub(lambda m: "#" * len(m.group(0)), texto)
    return achadas


def tipos_no_trecho(trecho: str) -> set[str]:
    """Os tipos de origem que o trecho mostra."""
    return set(expressoes_no_trecho(trecho))


def tipo_do_trecho(trecho: str) -> Optional[str]:
    """O tipo de origem que o trecho prova, ou None.

    - 1 tipo só: esse tipo.
    - Os 2 grupos federais: a defesa de 1ª instância decide. Com "impugnação"
      e sem "manifestação de inconformidade", o tipo é `auto_de_infracao`. No
      caso inverso, o tipo é `despacho_decisorio`. Nos outros casos, None.
    - `aiim` com um grupo federal: None. O trecho não decide entre os trilhos.
    - Nenhuma expressão: None.
    """
    achadas = expressoes_no_trecho(trecho)
    tipos = set(achadas)
    if len(tipos) == 1:
        return next(iter(tipos))
    if tipos != _FEDERAIS:
        return None
    com_defesa = [t for t, defesa in DEFESA_DE_1A_INSTANCIA.items()
                  if defesa in achadas.get(t, [])]
    return com_defesa[0] if len(com_defesa) == 1 else None


def lista_de_expressoes(tipo: str) -> str:
    """As expressões de um tipo, entre aspas e separadas por vírgula."""
    return ", ".join(f'"{e}"' for e in EXPRESSOES_ORIGEM[tipo])


def render_dicionario() -> str:
    """O dicionário em texto, 1 linha por tipo. O prompt usa esta função."""
    return "\n".join(f"- {tipo}: {lista_de_expressoes(tipo)}" for tipo in EXPRESSOES_ORIGEM)


__all__ = [
    "DEFESA_DE_1A_INSTANCIA",
    "EXPRESSOES_ORIGEM",
    "expressoes_no_trecho",
    "lista_de_expressoes",
    "normalizar",
    "render_dicionario",
    "tipo_do_trecho",
    "tipos_no_trecho",
]

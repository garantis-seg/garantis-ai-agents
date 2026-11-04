"""Fase A do redator v5 com function calling nativo do Gemini (R11, atrás de flag).

A recomendação R11 (Google, "Function calling") propõe declarar as ferramentas no
SDK em vez do protocolo em texto (um JSON na resposta). A decisão da casa é MEDIR
antes de trocar. Por isso os 2 protocolos convivem, e a flag de ambiente
`FICHA_FASE_A_NATIVA` escolhe um deles:

- Desligada (o default): o protocolo em texto, sem mudança (`ferramentas.DecisorTexto`).
- Ligada: o modelo recebe `tools` com uma `FunctionDeclaration` por ferramenta do menu
  e `tool_config` no modo `ANY`. A leitura termina com a função `terminar_leitura`.

O que NÃO muda entre os protocolos, de propósito, para a comparação valer:

- O menu fechado (`FERRAMENTAS`), o budget (25 por ficha, 5 por documento), o circuit
  breaker e a execução da ferramenta (`ferramentas.navegar` e `_executar`).
- A validação dos argumentos: `chamada_nativa` aplica as mesmas regras de
  `parse_chamada` (nome no menu, `args` em dict), e `_executar` aplica as demais
  (doc_id no índice, `pagina` inteira, `pergunta` ou `missao` não vazia).
- O resto do prompt. Só o bloco `<ferramentas>` muda (`prompts_v5.build_prompt_navegacao`).
- As métricas: `FaseAMetricas` sai na resposta nos 2 modos.

Um turno sem chamada de função válida conta como falha de protocolo, como o turno sem
JSON no modo texto. Não há fallback para o texto: o fallback apagaria a medida.
"""
from __future__ import annotations

from typing import Any, Optional

from .._utils.feature_flags import flag_enabled
from ..qualificador_conexo.ferramentas import FERRAMENTAS

#: A flag de ambiente. Ausente ou fora de {true, 1, yes, on} = protocolo em texto.
FLAG = "FICHA_FASE_A_NATIVA"

#: A função que encerra a fase A no protocolo nativo (o `{"fim": true}` do texto).
FERRAMENTA_FIM = "terminar_leitura"

#: O achado de um turno sem chamada de função válida.
ERRO_PROTOCOLO_NATIVO = "resposta sem chamada de função válida. Chame uma função do menu."

_DOC_ID = {"type": "string",
           "description": "Um item do ÍNDICE com legivel=true. O núcleo não precisa de ferramenta."}
_SLOT = {"type": "string", "description": "O slot para o qual a leitura serve."}

#: As declarações, uma por ferramenta do menu mais a de fim. As descrições repetem o
#: bloco `<ferramentas>` do protocolo em texto.
DECLARACOES: tuple[dict[str, Any], ...] = (
    {
        "name": "resumir_com_missao",
        "description": ("Primeira passada num documento longo: diz o que o documento tem "
                        "para a missão."),
        "parameters": {
            "type": "object",
            "properties": {"doc_id": _DOC_ID, "missao": {"type": "string"}, "slot": _SLOT},
            "required": ["doc_id", "missao"],
        },
    },
    {
        "name": "perguntar_ao_documento",
        "description": "Pergunta pontual. A resposta traz os trechos literais, com a página.",
        "parameters": {
            "type": "object",
            "properties": {"doc_id": _DOC_ID, "pergunta": {"type": "string"}, "slot": _SLOT},
            "required": ["doc_id", "pergunta"],
        },
    },
    {
        "name": "pedir_pagina",
        "description": "Texto cru de uma página. No máximo 3 páginas por documento.",
        "parameters": {
            "type": "object",
            "properties": {"doc_id": _DOC_ID, "pagina": {"type": "integer"}, "slot": _SLOT},
            "required": ["doc_id", "pagina"],
        },
    },
    {
        "name": FERRAMENTA_FIM,
        "description": ("Encerra a leitura: o núcleo e o que você leu bastam para escrever "
                        "todos os slots."),
    },
)

#: Modo ANY: o modelo sempre chama uma função. O menu inteiro fica permitido, porque o
#: circuit breaker fecha por (ferramenta, documento), e isso o prompt diz.
TOOL_CONFIG: dict[str, Any] = {
    "mode": "ANY",
    "allowed_function_names": [d["name"] for d in DECLARACOES],
}


def fase_a_nativa_ligada() -> bool:
    return flag_enabled(FLAG)


def modo_fase_a() -> str:
    return "nativo" if fase_a_nativa_ligada() else "texto"


def declaracoes() -> list[dict[str, Any]]:
    """Cópia das declarações, para o provider montar as `FunctionDeclaration`."""
    assert all(d["name"] in FERRAMENTAS or d["name"] == FERRAMENTA_FIM for d in DECLARACOES)
    return [dict(d) for d in DECLARACOES]


def chamada_nativa(function_calls: Any) -> Optional[dict[str, Any]]:
    """A chamada do turno, na forma de `parse_chamada`, ou None.

    Lê a PRIMEIRA chamada de função. Regras iguais às do texto: o nome está no menu
    (ou é a função de fim), e `args` é um dict (outra coisa vira `{}`).
    """
    if not isinstance(function_calls, list) or not function_calls:
        return None
    fc = function_calls[0]
    if not isinstance(fc, dict):
        return None
    nome = fc.get("name")
    if nome == FERRAMENTA_FIM:
        return {"fim": True}
    if isinstance(nome, str) and nome in FERRAMENTAS:
        args = fc.get("args")
        return {"tool": nome, "args": dict(args) if isinstance(args, dict) else {}}
    return None


class DecisorNativo:
    """O turno de decisão com function calling nativo (ver `ferramentas.Decisor`).

    A chamada vai sem temperature e sem seed: parâmetros no padrão do modelo (R13).
    A fase A NUNCA leva response_mime_type.
    """

    modo = "nativo"
    erro_protocolo = ERRO_PROTOCOLO_NATIVO

    def __init__(self, llm: Any, model: str):
        self.llm = llm
        self.model = model

    async def __call__(self, prompt: str, menu: list[str]) -> tuple[Any, Optional[dict]]:
        resp = await self.llm.agenerate(
            prompt=prompt,
            model=self.model,
            temperature=None,
            max_tokens=2048,
            tools=declaracoes(),
            tool_config=dict(TOOL_CONFIG),
        )
        calls = (getattr(resp, "metadata", None) or {}).get("function_calls")
        return resp, chamada_nativa(calls)


__all__ = [
    "DECLARACOES",
    "ERRO_PROTOCOLO_NATIVO",
    "FERRAMENTA_FIM",
    "FLAG",
    "TOOL_CONFIG",
    "DecisorNativo",
    "chamada_nativa",
    "declaracoes",
    "fase_a_nativa_ligada",
    "modo_fase_a",
]

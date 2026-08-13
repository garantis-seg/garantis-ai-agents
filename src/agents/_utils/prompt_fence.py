"""Fence anti prompt-injection — as 2 camadas, uma vez so.

Padrao da casa (QA-B1 achado B-3), usado por todo prompt que interpola texto de
TERCEIRO (dossie de tribunal, raw_json de provider, corpo de PDF). Vivia
copiado em `ficha_writer/prompts.py`; o C4 trouxe a 3a e a 4a copia, entao
virou modulo.

**Camada 1 — boundary aleatorio por request.** O conteudo cercado chega ao
prompt ANTES de o atacante poder observar o token; sem conhece-lo ele nao
consegue emitir a tag de fechamento e portanto nao fecha o fence. E o furo que
o fence fixo (`</dossie>`) tinha.

**Camada 2 — neutralizacao.** Cinto-e-suspensorio da camada 1: mesmo que o
token vazasse, o dado de terceiro ja chega sem nenhum `<` capaz de abrir tag.
"""

import json
import re
import secrets
from typing import Any

#: 8 bytes = 16 hex chars: imprevisivel o bastante para que o atacante nao
#: consiga escrever a tag de fechamento no dado que ele controla.
_FENCE_TOKEN_BYTES = 8

#: Qualquer `<` que abra uma tag (`<algo` ou `</algo`) — inclusive as tags de
#: fence dos proprios prompts.
_ABERTURA_DE_TAG = re.compile(r"<(?=/?[A-Za-z_])")


def gerar_fence_token() -> str:
    """Token hex NOVO a cada request — o boundary dos fences."""
    return secrets.token_hex(_FENCE_TOKEN_BYTES)


def neutralizar(texto: str) -> str:
    """Neutraliza aberturas de tag em texto de terceiro, virando `&lt;`.

    Escopo DELIBERADAMENTE estreito: so o `<` que inicia tag (`<x` / `</x`).
    Um `<` de comparacao ("valor < 100") fica INTACTO, porque nao forma tag —
    e num prompt de CALCULO isso importa mais que num de redacao.

    `&lt;` em vez de remocao preserva o texto legivel para o modelo. NAO quebra
    JSON: nao contem aspas nem barra invertida, e `<` nunca e pontuacao
    estrutural de JSON — trocamos o CONTEUDO do dado, jamais a pontuacao.
    """
    return _ABERTURA_DE_TAG.sub("&lt;", texto)


def sanitizar_valores(obj: Any) -> Any:
    """Aplica `neutralizar` recursivamente em TODA string — valores e CHAVES.

    Estrutura (dicts, listas, numeros, bool, None) preservada intacta: o objeto
    continua o mesmo, so o texto fica inerte.
    """
    if isinstance(obj, str):
        return neutralizar(obj)
    if isinstance(obj, dict):
        return {neutralizar(str(k)): sanitizar_valores(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitizar_valores(v) for v in obj]
    return obj


def json_sanitizado(obj: Any) -> str:
    """Serializa com todo texto ja neutralizado, e reneutraliza o JSON pronto.

    `default=str` (datas, Decimal, objetos exoticos) roda DENTRO do dumps, ou
    seja, DEPOIS da sanitizacao recursiva — por isso a neutralizacao final
    sobre o JSON ja montado.
    """
    body = json.dumps(sanitizar_valores(obj), ensure_ascii=False, indent=2, default=str)
    return neutralizar(body)


__all__ = ["gerar_fence_token", "neutralizar", "sanitizar_valores", "json_sanitizado"]

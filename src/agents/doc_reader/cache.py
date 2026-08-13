"""Cache do Leitor — LRU em memória, chave que versiona TUDO (§7.1).

ONDA 4. O desenho é explícito sobre por que esta camada existe e por que ela é
a mais perigosa do sistema: *"cache stale devolvendo resposta plausível e errada
em documento jurídico é o pior modo de falha do sistema inteiro, e é 100%
autoinfligido"* (§7.1, risco nº 1).

## A chave versiona tudo, e não tem TTL

    sha256("leitor/v1" \\x1f doc_hash \\x1f extractor_version \\x1f pergunta_canon
           \\x1f prompt_version \\x1f model \\x1f n_dinco)

Sete campos, e cada um responde a uma pergunta de invalidação diferente: o PDF
mudou? o extrator mudou? a pergunta é outra? o prompt mudou? o modelo mudou? o N
mudou? **Sem TTL** — TTL é palpite sobre quando algo mudou; versão é o fato de
que mudou. Um TTL de 1h não protege contra um deploy de prompt aos 5 minutos, e
atrapalha um cache válido por semanas.

⚑ SHA-256, nunca `hash()` builtin, e separador `\\x1f` entre as partes. O builtin
é salgado por processo (`PYTHONHASHSEED`) e dá valor diferente em cada container
do Cloud Run — o cache viraria uma função de qual instância atendeu. O separador
existe porque concatenar direto colide: `("ab","c")` e `("a","bc")` produziriam
a mesma string, e `\\x1f` (unit separator) não aparece em texto de documento. É a
mesma disciplina do `_utils/llm_seed.py::deterministic_seed`.

## Por que LRU em memória, e não o journal

O cache canônico do desenho é a onda 3 (`journal.py`), que ainda não está na
wheel consumida aqui — o `doc_indexer` da onda 2 declara `cache_hit: false` pelo
mesmo motivo. Um LRU por processo é o que se pode ter honestamente hoje: ele
paga o caso real (o Investigador repetindo a mesma pergunta dentro de uma
rodada, e as runs 2–5 do aceite Modo A dentro do mesmo container) e não mente
sobre o que não faz. Quando a onda 3 entrar, o que muda é o `_STORE` — a chave
já é a definitiva do §7.1, e é ela que tem que estar certa desde agora, porque
trocar a chave depois invalidaria um cache que já estaria em produção.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import OrderedDict
from typing import Any, Optional

__all__ = [
    "NAMESPACE_PERGUNTAR",
    "NAMESPACE_RESUMIR",
    "MAX_ENTRADAS",
    "canonicalizar_pergunta",
    "chave_leitor",
    "cache_get",
    "cache_put",
    "cache_clear",
    "cache_size",
]

#: Namespace por corpus (§7.1, regra 2). Prefixo diferente para as duas
#: ferramentas: uma pergunta pontual e uma missão ampla com o mesmo texto são
#: chamadas diferentes, com prompt e teto de saída diferentes, e colidi-las
#: devolveria um resumo onde se pediu uma resposta.
NAMESPACE_PERGUNTAR = "leitor/v1/perguntar"
NAMESPACE_RESUMIR = "leitor/v1/resumir"

#: Teto do LRU. Um dossiê grande tem dezenas de documentos e o Investigador faz
#: no máximo 40 tool calls por ficha (§8.6), então 512 cobre várias fichas
#: concorrentes no mesmo container sem virar um vazamento de memória disfarçado
#: de cache.
MAX_ENTRADAS = 512

#: `_STORE` é por PROCESSO, e isso é parte do contrato, não um detalhe: o Cloud
#: Run roda N instâncias e o hit é oportunista. Nada de correção pode depender
#: de um hit — o cache economiza, ele não decide.
_STORE: "OrderedDict[str, dict[str, Any]]" = OrderedDict()

_ESPACOS_RE = re.compile(r"\s+")


def canonicalizar_pergunta(pergunta: str) -> str:
    """NFKC + minúsculas + espaços colapsados (§7.1).

    "Qual o valor do IRPJ?" e "qual  o valor do irpj?" são a mesma pergunta e
    devem bater no mesmo cache. O que NÃO se canonicaliza é acento: `imposto` e
    `impôsto` podem ser palavras diferentes num documento antigo, e a economia
    de um hit a mais não paga uma resposta trocada.
    """
    texto = unicodedata.normalize("NFKC", str(pergunta or ""))
    return _ESPACOS_RE.sub(" ", texto).strip().lower()


def chave_leitor(
    *,
    namespace: str,
    doc_hash: str,
    extractor_version: str,
    pergunta: str,
    prompt_version: str,
    model: str,
    n_dinco: int,
) -> str:
    """A chave do §7.1. Todos os campos são obrigatórios — nomeados de propósito.

    Keyword-only porque são sete strings e trocar duas de posição produziria uma
    chave errada que **funciona**: o cache continuaria batendo, só que consigo
    mesmo, na partição errada. Esse é o tipo de bug que não aparece em teste de
    unidade e aparece em produção como resposta trocada.
    """
    partes = [
        namespace,
        str(doc_hash),
        str(extractor_version),
        canonicalizar_pergunta(pergunta),
        str(prompt_version),
        str(model),
        str(int(n_dinco)),
    ]
    return hashlib.sha256("\x1f".join(partes).encode("utf-8")).hexdigest()


def cache_get(chave: str) -> Optional[dict[str, Any]]:
    """A entrada, ou `None`. Renova a posição no LRU."""
    entrada = _STORE.get(chave)
    if entrada is None:
        return None
    _STORE.move_to_end(chave)
    # Cópia: o caller marca `cache_hit=True` e mexe no envelope, e uma
    # referência compartilhada faria a segunda leitura devolver o que a
    # primeira alterou.
    return dict(entrada)


def cache_put(chave: str, valor: dict[str, Any]) -> None:
    """Guarda e poda o mais antigo. Nunca levanta.

    Só se cacheia SUCESSO — quem chama filtra. Cachear uma falha faria um erro
    transitório de rede virar uma resposta negativa permanente para aquela
    pergunta, e o Investigador não teria como saber que o "não achei" que ele
    recebeu foi um timeout de meia hora atrás.
    """
    _STORE[chave] = dict(valor)
    _STORE.move_to_end(chave)
    while len(_STORE) > MAX_ENTRADAS:
        _STORE.popitem(last=False)


def cache_clear() -> None:
    """Zera o store. Para teste e para o Modo B do aceite (§7.5)."""
    _STORE.clear()


def cache_size() -> int:
    return len(_STORE)

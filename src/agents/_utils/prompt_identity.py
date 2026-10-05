"""Identidade DERIVADA do prompt — `sha256[:12]` do que de fato molda a saída do LLM.

## Por que isto existe

O `prompt_version` de cada agent é uma **string mantida à mão**, e por isso ela não se mexe
quando o prompt muda: a mudança que abaixa banda, e o revert dela, saem com o MESMO rótulo.
Consequência: a pergunta *"quais cards vieram do prompt ruim?"* fica **irrespondível** — só
sobra arqueologia por janela de timestamp, que pega card inocente e perde retry fora da
janela.

⭐ No card, o `summary_prompt_version` é a **chave de cache/rollout** — trocá-lo re-roda a
cascata no universo inteiro —, então é congelado por custo, não por esquecimento.
⛔ **NÃO reaproveite `summary_prompt_version` para isto**: `supersede_other_versions` faz
`UPDATE ... SET superseded_at=now() WHERE summary_prompt_version IS DISTINCT FROM
keep_version`, e um hash nunca casaria `keep_version` ⇒ o primeiro `enroll_processo`
aposentaria o histórico INTEIRO de cards do processo.

## Por que HASH DO ARQUIVO, e não dos blocos de regra

O hash de prompt + schema dá um número legível de baldes por trimestre, e é
**sobre-sensível na direção segura**: uma edição de comentário cria versão nova (ruído
barato) mas dois prompts diferentes **nunca** dividem um id. ⛔ Isolar as constantes de
template daria menos ruído e exigiria refatorar um módulo que decide a banda — risco
desproporcional ao ganho.

⭐ **O schema entra junto porque ele também molda a saída**: campo novo no `schemas_v4.py`
muda o comportamento do L1 sem tocar o prompt.

Propriedades (presas em `tests/test_prompt_identity.py`): reverter o arquivo restaura o id
antigo — "cards do prompt bom" é UM balde —, e a identidade é **por camada** (cada agent
hasheia os próprios arquivos), então não acusa mudança onde não houve.

## Precedente na casa

⭐ Não é desenho novo: `garantis_shared/calculo_fichas/journal.py` já deriva `prompt_version`
de `sha256[:n]` do template, com o raciocínio escrito — *"o template do prompt mudou ← deploy
ORFANA o antigo"* e *"Nada de TTL: TTL é palpite sobre quando a resposta apodrece"*. Isto só
aplica o mesmo idioma ao engine.
"""
from __future__ import annotations

import hashlib
import pathlib

_HASH_CHARS = 12


def prompt_identity(*arquivos: str) -> str:
    """`sha256[:12]` do conteúdo concatenado dos arquivos, na ordem dada.

    ⛔ **Fail-OPEN de propósito**: arquivo ilegível devolve `"unknown"` em vez de levantar.
    Este valor é telemetria — derrubar uma chamada de LLM paga porque um `read_bytes` falhou
    inverteria completamente a relação custo/benefício.

    ⚠️ A ORDEM importa (é concatenação, não soma): passe sempre na mesma ordem, senão o mesmo
    conteúdo produz ids diferentes.
    """
    h = hashlib.sha256()
    for f in arquivos:
        try:
            h.update(pathlib.Path(f).read_bytes())
        except OSError:
            return "unknown"
    return h.hexdigest()[:_HASH_CHARS]


def versao_com_identidade(rotulo: str, *arquivos: str) -> str:
    """`<rotulo>+<hash>` — mantém o rótulo humano E ganha a identidade derivada.

    ⭐ O rótulo fica porque ele é legível (`processo_synthesis.v2.5`) e porque é o que aparece
    em log e em painel; o hash entra porque ninguém precisa lembrar de bumpá-lo.

    ⚠️ **Ninguém casa `engine_llm_calls.prompt_version` por igualdade** (frontend-api e
    garantis-shared). Se um consumidor novo passar a casar, ele tem de casar por PREFIXO — o
    sufixo muda a cada edição, é esse o ponto.
    """
    return f"{rotulo}+{prompt_identity(*arquivos)}"

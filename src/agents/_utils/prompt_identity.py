"""Identidade DERIVADA do prompt — `sha256[:12]` do que de fato molda a saída do LLM.

## Por que isto existe

O `prompt_version` de cada agent é uma **string mantida à mão**, e por isso ela não se mexe
quando o prompt muda. Medido em 2026-08-23, na janela do incidente do PR #180 (uma mudança
de `<regra_polos>` que ABAIXAVA banda, revertida 13h depois):

| janela | `prompt_version` do L2 | n |
|---|---|---:|
| ANTES do #180 | `processo_synthesis.v2.5` | 137 |
| **DURANTE** | `processo_synthesis.v2.5` | 35 |
| DEPOIS do revert | `processo_synthesis.v2.5` | 24 |

**Idêntico nas três.** Consequência: a pergunta *"quais cards vieram do prompt ruim?"* é
**irrespondível** — só sobra arqueologia por janela de timestamp, que pega card inocente e
perde retry fora da janela.

⭐ O mesmo já vale pro card: `summary_prompt_version` está em `v7.0` em **todos** os 251
`processo_synthesis` e 25.109 `mov_factsheet` de 19/08 até hoje. Lá o campo é a **chave de
cache/rollout** — trocá-lo re-roda a cascata no universo inteiro —, então é congelado por
custo, não por esquecimento. ⛔ **NÃO reaproveite `summary_prompt_version` para isto**:
`supersede_other_versions` faz `UPDATE ... SET superseded_at=now() WHERE
summary_prompt_version IS DISTINCT FROM keep_version`, e um hash nunca casaria `keep_version`
⇒ o primeiro `enroll_processo` aposentaria o histórico INTEIRO de cards do processo.

## Por que HASH DO ARQUIVO, e não dos blocos de regra

Medido no histórico de 90 dias (`git log` + `git rev-parse <commit>:<file>`):

| granularidade | versões distintas em 90d |
|---|---:|
| hoje (string à mão) | **1** |
| só o prompt | 19 (L2) · 22 (L1) |
| **prompt + schema** | **25 · 25** |

25 baldes em 3 meses é legível, e o hash é **sobre-sensível na direção segura**: uma edição
de comentário cria versão nova (ruído barato) mas dois prompts diferentes **nunca** dividem
um id. ⛔ Isolar as constantes de template daria menos ruído e exigiria refatorar um módulo
que decide a banda — risco desproporcional ao ganho.

⭐ **O schema entra junto porque ele também molda a saída**: o campo `dispositivo` (PR #182)
mudou o comportamento do L1 mexendo em `schemas_v4.py`. Custo de incluí-lo: ~6 baldes a mais
por trimestre.

## Validado contra o incidente real

- `663e7b0` (#180) e `9f53855` (revert) ⇒ **blobs diferentes**: o hash teria distinguido.
- O revert restaurou o blob pré-#180 **byte-idêntico** ⇒ "cards do prompt bom" é UM balde.
- `3c64207` (o `dispositivo`, que mexeu só no L1) tem o **mesmo** blob de L2 do revert ⇒ a
  identidade é **por camada** e não acusa mudança onde não houve.

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

    ⚠️ Verificado antes de mudar o formato: **ninguém casa `engine_llm_calls.prompt_version`
    por igualdade** (grep em frontend-api + garantis-shared, 2026-08-23). Se um consumidor
    novo passar a casar, ele tem de casar por PREFIXO — o sufixo muda a cada edição, é esse
    o ponto.
    """
    return f"{rotulo}+{prompt_identity(*arquivos)}"

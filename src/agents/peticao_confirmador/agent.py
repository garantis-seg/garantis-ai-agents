"""Peticao Confirmador Agent -- o C5, confirmador COMPARATIVO da peticao inicial.

UMA chamada LLM barata (text-only, sem Vision) que recebe os N candidatos JUNTOS,
numerados, e responde qual deles e a peca inaugural DESTE processo -- ou 0, que e
uma resposta certa e esperada.

## Por que ele existe

Ate agora a afirmacao *"este documento e a peticao inicial"* era DEDUZIDA DO
PREFIXO DA CAMADA que achou o documento, e ninguem LIA o documento pra decidir.
Com o C5 as 5 camadas (C1..C4, X1) viram GERADORAS DE CANDIDATOS e quem AFIRMA e
esta leitura paga e comparativa, com abstencao explicita. ⛔ Nenhuma camada e
deletada -- elas sao REBAIXADAS; o degrau continua sendo o que acha o material.

## O FRAME e tudo

  · frame INDUTOR (1 doc isolado, "isto e a inicial? s/n") -- medido 4.228x em
    producao: responde `peticao_inicial` em 49,2% dos C4 quando a verdade e ~3%.
    Foi ele que fabricou os 411 cards errados que este pacote existe pra desfazer.
  · frame COMPARATIVO (este) -- medido no gold adjudicado N=22: afirma e ACERTA
    21/22; no CONTROLE NEGATIVO (o doc do gold REMOVIDO do conjunto) afirma 1/22.
    Fisher exato 1-cauda p = 2,19e-11 ⇒ a abstencao e condicionada ao CONTEUDO,
    nao e retorica do prompt.

⛔ **Nao troque esta UMA chamada por N chamadas de 1 documento.** Isso e trocar o
frame comparativo pelo indutor, e o resto do pacote (o `garantis_shared` promove a
resposta a uma camada AFIRMATIVA por construcao) nao tem como perceber.
⛔ E a barra de 90% do dono **nao foi vencida estatisticamente** -- com N=22 nao
podia ser (LCB95 = 80,2%). ⛔ Nao escreva "bate 90%" em PR, card, comentario ou
audit log. O que o C5 compra e a afirmacao passar a ter LASTRO PAGO onde hoje ela
e deduzida do prefixo.

## Espelha o `mov_triage`

Mesmo desenho: 1 chamada barata, text-only, `thinking_budget=0`, card malformado
-> error dict e o caller trata como falha. ⭐ E a falha aqui e BARATA por desenho:
do lado do `garantis_shared` qualquer erro (404, 5xx, timeout, JSON fora do
contrato) vira ABSTENCAO, que e o estado de HOJE -- o pn fica exatamente onde ja
esta e volta na proxima passada.
"""

from __future__ import annotations

import logging
import os
import pathlib
from typing import Any, Optional

from ...providers import create_provider
from ...providers.base import LLMResponse
from ...utils.llm_json import parse_llm_json
from .._utils import MODEL_VARIANT_TEXT
from .._utils.prompt_identity import versao_com_identidade
from .prompts import build_confirmador_prompt
from .schemas import CONFIRMADOR_RESPONSE_SCHEMA

logger = logging.getLogger(__name__)

# ⭐⭐ O MODELO E UM PARAMETRO MEDIDO, nao uma politica -- por isso ele e literal
# aqui e nao `model_for("engine_layer1")`. O papel `engine_layer1` aponta pro MESMO
# modelo hoje, mas ele existe pra ser trocado por decisao de custo/qualidade do L1;
# amarrar o confirmador nele faria um bump do L1 trocar o modelo desta camada em
# silencio, e o 21/22 deixaria de descrever o que roda. As 4 varreduras (POS_A/B/C +
# os 2 controles negativos) rodaram em `gemini-3.1-flash-lite`.
# ⛔ NUNCA usar `gemini-3.1-flash` NAO-lite -- nao existe no Vertex (404).
# ⚠️ Se um dia isto virar papel, o lugar e `garantis_shared.llm_models.ROLES`.
DEFAULT_MODEL = os.getenv("PETICAO_CONFIRMADOR_MODEL", "gemini-3.1-flash-lite")
DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER", "gemini")

# Teto de saida do arnes. tok_out MAXIMO medido = 158 -- o teto e folga, nao alvo.
_MAX_TOKENS = 2048

# ⭐ DERIVADA, nao mantida a mao -- razao e medicoes em `_utils/prompt_identity.py`.
# Os 3 arquivos entram porque os 3 moldam a saida: `prompts.py` (o texto),
# `schemas.py` (o `response_schema` que o provider aplica) e ESTE arquivo (modelo,
# temperatura, `thinking_budget`, teto de tokens). ⛔ O `garantis_shared` usa
# `"peticao_confirmador.v1"` como FALLBACK quando o ai-agents nao devolve nada, e
# ele casa por... nada: ninguem casa `prompt_version` por igualdade nesta casa. Se
# um consumidor novo passar a casar, tem de casar por PREFIXO.
PROMPT_VERSION = versao_com_identidade(
    "peticao_confirmador.v1",
    str(pathlib.Path(__file__).with_name("prompts.py")),
    str(pathlib.Path(__file__).with_name("schemas.py")),
    __file__,
)


async def confirmar_peticao(
    processo: Any,
    candidatos: list[Any],
    head_chars: int,
    model: Optional[str] = None,
    provider: str = DEFAULT_PROVIDER,
) -> dict:
    """Julga os N candidatos JUNTOS. 1 LLM call, veredito 0..N.

    Args:
        processo: contexto do processo (so 6 campos dele chegam ao prompt).
        candidatos: o pool, na ordem em que sera apresentado. A POSICAO e a
            numeracao -- `escolhido = k` significa `candidatos[k - 1]`.
        head_chars: a janela declarada pelo caller (dono: `garantis_shared`).
        model: override do modelo.
        provider: 'gemini' (default).

    Returns:
        {"card": {"escolhido", "continuacao", "motivo"} | error_dict,
         "raw_response": str,
         "llm_raw_prompt": str,
         "prompt_version": str,
         "usage": dict}
    """
    proc = processo if isinstance(processo, dict) else processo.model_dump()
    cands = [c if isinstance(c, dict) else c.model_dump() for c in candidatos]

    if model is None:
        model = DEFAULT_MODEL

    llm_provider = create_provider(provider)
    sistema, usuario = build_confirmador_prompt(proc, cands, head_chars)

    # ⛔ `temperature=0.0` + `top_p=1.0` + `top_k=1` sao os parametros MEDIDOS
    # (determinismo 12/12 com prompt byte-identico). O provider ja forca top_p/top_k
    # quando `temperature == 0.0`; eles vao explicitos porque sao parte do que foi
    # medido, e um default que muda nao pode mudar esta camada calada.
    # ⭐ `thinking_budget=0`: prompt curto e decisao de leitura, nao de raciocinio --
    # e o mesmo regime do L1 de extracao (43/43 campos identicos com e sem thinking).
    response: LLMResponse = await llm_provider.agenerate(
        prompt=usuario,
        model=model,
        temperature=0.0,
        max_tokens=_MAX_TOKENS,
        response_schema=CONFIRMADOR_RESPONSE_SCHEMA,
        system_instruction=sistema,
        top_p=1.0,
        top_k=1,
        thinking_budget=0,
    )

    raw_response = response.text
    try:
        card_data: dict = parse_llm_json(raw_response)
    except Exception as e:
        logger.error("peticao_confirmador parse failed: %r", e)
        card_data = {"error": repr(e), "raw": raw_response}

    # 🚨 CONTADOR POSITIVO E COM DENOMINADOR. `escolhido=0 de=6` = passo OCIOSO
    # (avaliou 6 e nao afirmou nenhum); LINHA AUSENTE = passo MUDO. O modo de falha
    # desta classe e "nao afirmar o que importava", que e invisivel -- por isso a
    # linha sai SEMPRE, inclusive quando o card veio quebrado, e nunca pendurada
    # num `if`. O `doc_key` aparece aqui, e SO aqui: e pra isso que ele vem.
    escolhido = card_data.get("escolhido") if isinstance(card_data, dict) else None
    logger.info(
        "PETICAO_CONFIRMADOR escolhido=%s de=%d head_chars=%d doc_key=%s model=%s",
        escolhido, len(cands), head_chars,
        (cands[escolhido - 1].get("doc_key")
         if isinstance(escolhido, int) and not isinstance(escolhido, bool)
         and 1 <= escolhido <= len(cands) else None),
        model,
    )

    usage = {
        "input_tokens": response.input_tokens or 0,
        "output_tokens": response.output_tokens or 0,
        "total_tokens": (response.input_tokens or 0) + (response.output_tokens or 0),
        "cached_tokens": getattr(response, "cached_tokens", 0) or 0,
        "cost_usd": (response.metadata.get("cost_usd", 0.0) if response.metadata else 0.0),
        "model": model,
        "provider": provider,
        "model_variant": (
            response.metadata.get("model_variant", MODEL_VARIANT_TEXT)
            if response.metadata else MODEL_VARIANT_TEXT
        ),
    }

    return {
        "card": card_data,
        "raw_response": raw_response,
        # ⭐ O que o modelo VIU, inteiro, num campo so -- o `system_instruction` vai
        # separado no fio, mas quem debuga (e o guard de vazamento) precisa do texto
        # completo. ⛔ Nao reduza ao `usuario`: metade do frame mora no `sistema`.
        "llm_raw_prompt": f"{sistema}\n\n{usuario}",
        "prompt_version": PROMPT_VERSION,
        "usage": usage,
    }

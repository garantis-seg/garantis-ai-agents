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

## O candidato SCAN (fatia 2 da cabeca dos autos, card 869equgwd)

Doc da cabeca sem teor chega com `head` vazio + `gcs_url`. O Vision **so TRANSCREVE** as N
primeiras paginas dele, e a transcricao vira o `head` — o julgamento continua sendo a MESMA
chamada de texto, com o frame medido. ⛔⛔ Nao ponha o PDF na chamada que JULGA (decisao
Elton 15/09, gold scan): misturado, o PDF quebrou o determinismo e contaminou o julgamento do
texto (FP 1 em 3 no mesmo pool); numa chamada so de scans, o modelo perdeu o contraste e
afirmou inicial de OUTRO processo em 3/22. Vision extrai; quem afirma e o C5 de texto.
"""

from __future__ import annotations

import asyncio
import logging
import os
import pathlib
from typing import Any, Optional

from ...providers import create_provider
from ...providers.base import LLMResponse
from ...utils.llm_json import parse_llm_json
from .._utils import MODEL_VARIANT_TEXT, MODEL_VARIANT_VISION
from .._utils.ocr_gate import inicio_do_pdf
from .._utils.prompt_identity import versao_com_identidade
from .._utils.vision import call_vision_l1, fetch_pdfs_from_gcs
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

# A TRANSCRICAO do scan. ⛔ Extracao, nunca julgamento: nada de "e a peticao inicial?" aqui —
# essa pergunta e da chamada comparativa, e so dela.
_TRANSCREVA = ("Transcreva LITERALMENTE o texto das paginas deste PDF, na ordem em que "
               "aparece, sem resumir, sem comentar e sem corrigir. Se uma pagina nao tiver "
               "texto legivel, escreva [ilegivel]. Responda somente com a transcricao.")
# ~3.000 chars de janela ≈ 1.000 tokens; o teto e folga pra 2 paginas densas.
_MAX_TOKENS_TRANSCRICAO = 2048
_SEED_TRANSCRICAO = 915
_MARCA_SEM_PDF = "[documento digitalizado sem texto extraivel; PDF indisponivel]"


async def _transcreve_scans(llm_provider, cands: list[dict], head_paginas: int, model: str,
                            ) -> tuple[int, list[LLMResponse], list[LLMResponse], int]:
    """`head` vazio + `gcs_url` -> a transcricao das `head_paginas` primeiras paginas.

    1 chamada POR documento, de proposito: com varios PDFs numa chamada so, o modelo casou
    "candidato 3" com "o 3o PDF" (gold scan 15/09). Falha de fetch/corte/Vision vira a marca
    `_MARCA_SEM_PDF` — o candidato segue no pool, sem conteudo, e o C5 nao o afirma.

    🚨 As DUAS falhas nao sao a mesma coisa, e o 4o item do retorno e o que as separa pro
    caller (o `garantis_shared` le `usage.transcricoes_falhas`):
      · PDF ILEGIVEL (nao baixou, stub de "acesso restrito", HTML servido como .pdf, nao
        recorta) — e do ARQUIVO, DETERMINISTICO: a proxima passada daria a mesma marca. O C5
        julgar sem ele e uma decisao valida sobre o que existe. ⚠️ Medido 24/09: as 27 falhas
        dos 30 dias eram TODAS deste tipo (arquivos de 31-502 B e um XHTML de 9,5 KB no GCS).
      · EXCECAO do Vision (429/timeout/5xx) ou do cliente do GCS — e do CAMINHO, TRANSITORIA:
        o C5 julgou com um candidato CEGO que a proxima passada leria. E ela que vai contada,
        pra o caller NAO gravar essa abstencao como decisao (senao o pre-guard congela o pool
        para sempre).
    ⚠️ Limite conhecido: o `fetch_pdfs_from_gcs` engole o erro do DOWNLOAD de cada PDF e
    devolve lista vazia, entao um download que falhou por rede cai no 1o tipo."""
    def _excecao(c: dict, exc: Exception) -> tuple[None, bool]:
        logger.warning("PETICAO_CONFIRMADOR_TRANSCRICAO_FALHOU doc_key=%s tipo=excecao erro=%r",
                       c.get("doc_key"), exc)
        c["head"] = _MARCA_SEM_PDF
        return None, True

    async def _um(c: dict) -> tuple[LLMResponse | None, bool]:
        try:
            baixados = await fetch_pdfs_from_gcs([c["gcs_url"]])
        except Exception as exc:   # o cliente do GCS que nem sobe (credencial, rede)
            return _excecao(c, exc)
        corte = inicio_do_pdf(baixados[0], head_paginas) if baixados else None
        if corte is None:
            logger.warning("PETICAO_CONFIRMADOR_TRANSCRICAO_FALHOU doc_key=%s tipo=pdf_ilegivel"
                           " erro=%r", c.get("doc_key"),
                           ValueError("PDF indisponivel ou nao recortavel"))
            c["head"] = _MARCA_SEM_PDF
            return None, False
        try:
            r = await call_vision_l1(llm_provider, model=model, prompt=_TRANSCREVA,
                                     pdf_bytes_list=[corte], temperature=0.0,
                                     thinking_budget=0, max_tokens=_MAX_TOKENS_TRANSCRICAO,
                                     seed=_SEED_TRANSCRICAO)
        except Exception as exc:
            return _excecao(c, exc)
        c["head"] = (r.text or "").strip() or _MARCA_SEM_PDF
        return r, False

    # ⭐ EM PARALELO (review 15/09): em serie, 4 scans lentos estouravam o timeout do caller, e
    # o retry dele re-pagava todas as transcricoes. Cada uma escreve so no PROPRIO candidato.
    scans = [c for c in cands if not c.get("head") and c.get("gcs_url")]
    saidas = await asyncio.gather(*(_um(c) for c in scans))
    respostas = [r for r, _ in saidas]
    # `transcritos` conta so o que virou texto — transcricao vazia (bloqueio) e marca, nao leitura.
    return (len(scans),
            [r for r, c in zip(respostas, scans) if r is not None and c["head"] != _MARCA_SEM_PDF],
            [r for r in respostas if r is not None],
            sum(1 for _, falhou in saidas if falhou))


async def confirmar_peticao(
    processo: Any,
    candidatos: list[Any],
    head_chars: int,
    model: Optional[str] = None,
    provider: str = DEFAULT_PROVIDER,
    head_paginas: int = 2,
) -> dict:
    """Julga os N candidatos JUNTOS. 1 LLM call de julgamento, veredito 0..N.

    Args:
        processo: contexto do processo (so 6 campos dele chegam ao prompt).
        candidatos: o pool, na ordem em que sera apresentado. A POSICAO e a
            numeracao -- `escolhido = k` significa `candidatos[k - 1]`.
        head_chars: a janela declarada pelo caller (dono: `garantis_shared`).
        model: override do modelo.
        provider: 'gemini' (default).
        head_paginas: a janela em PAGINAS do candidato scan (dono: `garantis_shared`).

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
    n_scans, transcricoes, pagas, falhas = await _transcreve_scans(llm_provider, cands,
                                                                   head_paginas, model)
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
    # `scans=` quantos vieram sem texto; `transcritos=` quantos o Vision leu; `falhas=` quantos
    # nao foram lidos por EXCECAO (ver `_transcreve_scans`).
    escolhido = card_data.get("escolhido") if isinstance(card_data, dict) else None
    logger.info(
        "PETICAO_CONFIRMADOR escolhido=%s de=%d scans=%d transcritos=%d falhas=%d head_chars=%d"
        " doc_key=%s model=%s",
        escolhido, len(cands), n_scans, len(transcricoes), falhas, head_chars,
        (cands[escolhido - 1].get("doc_key")
         if isinstance(escolhido, int) and not isinstance(escolhido, bool)
         and 1 <= escolhido <= len(cands) else None),
        model,
    )

    todas = [response, *pagas]   # custo = toda transcricao que respondeu, vazia ou nao
    usage = {
        "input_tokens": sum(r.input_tokens or 0 for r in todas),
        "output_tokens": sum(r.output_tokens or 0 for r in todas),
        "total_tokens": sum((r.input_tokens or 0) + (r.output_tokens or 0) for r in todas),
        "cached_tokens": getattr(response, "cached_tokens", 0) or 0,
        # 🚨 A transcricao entra no custo: sem ela o contador da lane leria o scan de graca.
        "cost_usd": sum((r.metadata or {}).get("cost_usd", 0.0) for r in todas),
        "model": model,
        "provider": provider,
        "model_variant": MODEL_VARIANT_VISION if transcricoes else (
            response.metadata.get("model_variant", MODEL_VARIANT_TEXT)
            if response.metadata else MODEL_VARIANT_TEXT
        ),
        # ⭐ O CONTRATO com o `garantis_shared` (`_confirma_peticao`): `transcricoes_falhas > 0`
        # ⇒ o veredito NAO vale como decisao (o frame teve candidato CEGO por excecao). ⛔ O PDF
        # ilegivel NAO entra nela — ver `_transcreve_scans`. Caller antigo ignora as chaves.
        "scans": n_scans,
        "transcritos": len(transcricoes),
        "transcricoes_falhas": falhas,
    }

    return {
        "card": card_data,
        "raw_response": raw_response,
        # ⭐ O que o modelo VIU, inteiro, num campo so -- o `system_instruction` vai
        # separado no fio, mas quem debuga (e o guard de vazamento) precisa do texto
        # completo. ⛔ Nao reduza ao `usuario`: metade do frame mora no `sistema`.
        # A transcricao do scan ja esta dentro dele, como `head`.
        "llm_raw_prompt": f"{sistema}\n\n{usuario}",
        "prompt_version": PROMPT_VERSION,
        "usage": usage,
    }

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
from .._utils.ocr_gate import inicio_do_pdf
from .._utils.prompt_identity import versao_com_identidade
from .._utils.vision import (MODEL_VARIANT_VISION, _INLINE_PER_PDF_BYTES_CAP,
                             _INLINE_TOTAL_BYTES_CAP, call_vision_l1, fetch_pdfs_from_gcs)
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

# ⭐ O CANDIDATO SCAN (fatia 2 da cabeca dos autos, card 869equgwd, OK Elton 2026-09-15).
# Doc da cabeca sem teor chega com `head` vazio + `gcs_url` e e julgado numa 2a chamada,
# SO DE SCANS, com as N primeiras paginas inline.
# ⛔⛔ SEPARADA, e nao misturada ao pool de texto (decisao Elton 15/09, gold scan): com os PDFs
# na mesma chamada o C5 perdeu o determinismo medido (o MESMO pool deu FP 1 em 3) e passou a
# afirmar um DESPACHO de texto que so-texto abstem. Separadas, a chamada de texto e a de hoje,
# byte a byte, e o PDF nao contamina o julgamento dela.
# ⛔ `SISTEMA`/`USUARIO`/`BLOCO` NAO mudam (sha256 guardado); a marca so aponta o PDF.
# ⭐⭐ O rotulo e a POSICAO DO CANDIDATO, nunca a ordem do anexo: com "PDF anexo numero k" o
# modelo casou "candidato 3" com "o 3o PDF" (1 afirmacao errada + 2 iniciais perdidas).
_ROTULO_PDF = "PDF DO CANDIDATO [{i}]"
_MARCA_PDF = ("[documento digitalizado sem texto extraivel: o INICIO dele sao as "
              "{p} primeiras paginas do arquivo rotulado " + _ROTULO_PDF + "]")
_MARCA_SEM_PDF = "[documento digitalizado sem texto extraivel; PDF indisponivel]"
# Seed FIXO so no ramo Vision: o de texto foi medido sem seed (12/12) e fica como esta.
_SEED_SCAN = 915


def _e_scan(c: dict) -> bool:
    return not c.get("head") and bool(c.get("gcs_url"))


async def _anexa_pdfs_dos_scans(cands: list[dict],
                                head_paginas: int) -> tuple[list[bytes], list[str]]:
    """Troca o `head` vazio dos scans pela marca e devolve os PDFs cortados + o rotulo de
    cada um (`PDF DO CANDIDATO [i]`, i = posicao NESTA chamada).

    ⛔ Os caps inline sao aplicados AQUI, antes de rotular: o `_build_pdf_parts` dropa o
    que nao cabe, e um drop depois faria a marca apontar um PDF que nao subiu. Mesma greedy,
    mesma ordem — e o `call_vision_l1` ainda levanta se rotulo e PDF desalinharem."""
    pdfs: list[bytes] = []
    rotulos: list[str] = []
    total = 0
    for i, c in enumerate(cands, 1):
        baixados = await fetch_pdfs_from_gcs([c["gcs_url"]])
        corte = inicio_do_pdf(baixados[0], head_paginas) if baixados else None
        if (corte is None or len(corte) > _INLINE_PER_PDF_BYTES_CAP
                or total + len(corte) > _INLINE_TOTAL_BYTES_CAP):
            c["head"] = _MARCA_SEM_PDF
            continue
        pdfs.append(corte)
        rotulos.append(_ROTULO_PDF.format(i=i))
        total += len(corte)
        c["head"] = _MARCA_PDF.format(p=head_paginas, i=i)
    return pdfs, rotulos


async def _julga(llm_provider, proc: dict, cands: list[dict], head_chars: int, model: str,
                 pdfs: list[bytes] | None = None, rotulos: list[str] | None = None) -> dict:
    """UMA chamada comparativa sobre `cands` (numerados 1..len). Devolve o card cru + o fio."""
    sistema, usuario = build_confirmador_prompt(proc, cands, head_chars)
    # ⛔ `temperature=0.0` + `top_p=1.0` + `top_k=1` sao os parametros MEDIDOS
    # (determinismo 12/12 com prompt byte-identico). O provider ja forca top_p/top_k
    # quando `temperature == 0.0`; eles vao explicitos porque sao parte do que foi
    # medido, e um default que muda nao pode mudar esta camada calada.
    # ⭐ `thinking_budget=0`: prompt curto e decisao de leitura, nao de raciocinio --
    # e o mesmo regime do L1 de extracao (43/43 campos identicos com e sem thinking).
    comuns = dict(model=model, temperature=0.0, max_tokens=_MAX_TOKENS,
                  response_schema=CONFIRMADOR_RESPONSE_SCHEMA,
                  system_instruction=sistema, top_p=1.0, top_k=1, thinking_budget=0)
    if pdfs:
        response: LLMResponse = await call_vision_l1(
            llm_provider, prompt=usuario, pdf_bytes_list=pdfs, rotulos=rotulos,
            seed=_SEED_SCAN, **comuns)
    else:
        response = await llm_provider.agenerate(prompt=usuario, **comuns)
    try:
        card: dict = parse_llm_json(response.text)
    except Exception as e:
        logger.error("peticao_confirmador parse failed: %r", e)
        card = {"error": repr(e), "raw": response.text}
    return {"card": card, "response": response, "prompt": f"{sistema}\n\n{usuario}"}


def _para_global(k: Any, posicoes: list[int], n_total: int) -> Any:
    """Indice LOCAL (1..len(posicoes)) -> GLOBAL. ⛔ Fora de faixa/tipo passa como invalido
    GLOBAL (n_total+1 ou o valor cru), pra o `_valida_veredito` do shared continuar dono da
    regra — nunca vira um indice valido por acidente."""
    if isinstance(k, bool) or not isinstance(k, int):
        return k
    if k == 0:
        return 0
    return posicoes[k - 1] if 1 <= k <= len(posicoes) else n_total + 1


async def confirmar_peticao(
    processo: Any,
    candidatos: list[Any],
    head_chars: int,
    model: Optional[str] = None,
    provider: str = DEFAULT_PROVIDER,
    head_paginas: int = 2,
) -> dict:
    """Julga os N candidatos. Veredito 0..N na numeracao do pool recebido.

    Pool sem scan: 1 chamada de texto, exatamente a de antes. Pool com scan: a de texto
    sobre os candidatos de texto + 1 Vision sobre os scans; as duas respostas voltam pra
    numeracao global. ⛔ As duas afirmando = ABSTENCAO (apontar errado e pior).

    Returns:
        {"card": {"escolhido", "continuacao", "motivo"} | error_dict,
         "raw_response": str, "llm_raw_prompt": str, "prompt_version": str, "usage": dict}
    """
    proc = processo if isinstance(processo, dict) else processo.model_dump()
    cands = [c if isinstance(c, dict) else c.model_dump() for c in candidatos]
    model = model or DEFAULT_MODEL
    llm_provider = create_provider(provider)

    pos_texto = [i for i, c in enumerate(cands, 1) if not _e_scan(c)]
    pos_scan = [i for i, c in enumerate(cands, 1) if _e_scan(c)]
    julgados: list[tuple[list[int], dict]] = []
    n_pdfs = 0
    if pos_texto:
        julgados.append((pos_texto, await _julga(
            llm_provider, proc, [cands[i - 1] for i in pos_texto], head_chars, model)))
    if pos_scan:
        scans = [cands[i - 1] for i in pos_scan]
        pdfs, rotulos = await _anexa_pdfs_dos_scans(scans, head_paginas)
        n_pdfs = len(pdfs)
        if pdfs:   # ⛔ nenhum PDF subiu: nao ha o que ler, nao se paga pergunta vazia
            julgados.append((pos_scan, await _julga(
                llm_provider, proc, scans, head_chars, model, pdfs, rotulos)))

    erro = next((j["card"] for _, j in julgados if not isinstance(j["card"], dict)
                 or "error" in j["card"]), None)
    if erro is not None:
        card_data: dict = erro if isinstance(erro, dict) else {"error": "card nao e objeto"}
    elif len(julgados) == 1 and len(julgados[0][0]) == len(cands):
        # ⛔ UMA chamada sobre o pool inteiro: o card sai CRU, como sempre saiu — o
        # `_valida_veredito` do shared e o dono de fora-de-faixa e fora-de-tipo, e remapear
        # aqui transformaria `99` num indice valido ou `false` numa abstencao.
        card_data = julgados[0][1]["card"]
    else:
        # ⛔ So `0` INTEIRO e abstencao: `False == 0` em Python, e bool/str/float tem de chegar
        # ao shared como afirmacao invalida, nao sumir como "nao afirmou".
        afirmam = [(p, j["card"]) for p, j in julgados
                   if not (type(j["card"].get("escolhido")) is int
                           and j["card"].get("escolhido") == 0)]
        if not afirmam:
            card_data = {"escolhido": 0, "continuacao": [],
                         "motivo": " | ".join(str(j["card"].get("motivo") or "")
                                              for _, j in julgados)}
        elif len(afirmam) > 1:
            card_data = {"escolhido": 0, "continuacao": [],
                         "motivo": "texto e scan afirmaram documentos diferentes: abstencao"}
        else:
            p, c = afirmam[0]
            card_data = {
                "escolhido": _para_global(c.get("escolhido"), p, len(cands)),
                "continuacao": [_para_global(k, p, len(cands))
                                for k in (c.get("continuacao") or [])],
                "motivo": c.get("motivo") or "",
            }

    # 🚨 CONTADOR POSITIVO E COM DENOMINADOR. `escolhido=0 de=6` = passo OCIOSO
    # (avaliou 6 e nao afirmou nenhum); LINHA AUSENTE = passo MUDO. O modo de falha
    # desta classe e "nao afirmar o que importava", que e invisivel -- por isso a
    # linha sai SEMPRE, inclusive quando o card veio quebrado, e nunca pendurada
    # num `if`. O `doc_key` aparece aqui, e SO aqui: e pra isso que ele vem.
    escolhido = card_data.get("escolhido")
    logger.info(
        "PETICAO_CONFIRMADOR escolhido=%s de=%d scans=%d pdfs=%d chamadas=%d head_chars=%d"
        " doc_key=%s model=%s",
        escolhido, len(cands), len(pos_scan), n_pdfs, len(julgados), head_chars,
        (cands[escolhido - 1].get("doc_key")
         if isinstance(escolhido, int) and not isinstance(escolhido, bool)
         and 1 <= escolhido <= len(cands) else None),
        model,
    )

    resps = [j["response"] for _, j in julgados]
    tin = sum(r.input_tokens or 0 for r in resps)
    tout = sum(r.output_tokens or 0 for r in resps)
    usage = {
        "input_tokens": tin,
        "output_tokens": tout,
        "total_tokens": tin + tout,
        "cached_tokens": sum(getattr(r, "cached_tokens", 0) or 0 for r in resps),
        "cost_usd": sum((r.metadata or {}).get("cost_usd", 0.0) for r in resps),
        "model": model,
        "provider": provider,
        "model_variant": MODEL_VARIANT_VISION if n_pdfs else MODEL_VARIANT_TEXT,
    }

    return {
        "card": card_data,
        "raw_response": "\n\n".join(r.text or "" for r in resps),
        # ⭐ O que o modelo VIU, inteiro -- o `system_instruction` vai separado no fio, mas
        # quem debuga (e o guard de vazamento) precisa do texto completo. Com scan, as 2
        # chamadas vao concatenadas. ⛔ Nao reduza ao `usuario`: metade do frame mora no `sistema`.
        "llm_raw_prompt": "\n\n".join(j["prompt"] for _, j in julgados),
        "prompt_version": PROMPT_VERSION,
        "usage": usage,
    }

"""Classificador ESTREITO de celula-base (D1, decisao Elton 2026-07-11).

Uma leitura ESTREITA por merito (NAO a sintese grande do B1): dado o dossie coerente, classifica
contra a convencao da adjudicacao verificada -- celula-base = garantia aceita + divida adversa VIVA
suspensa SEM sinal favoravel governante. O sinal alimenta o PISO deterministico celula-base do L3
(derive_risco_celula_base_floor) que so ELEVA Baixo->Medio (surety-safe; a POLITICA continua
deterministica/auditavel, o LLM so LE a polaridade que os sinais estruturados nao resolvem).

Confiabilidade = N=3 (temp0, seeds VARIANDO) -> UNANIME sustenta o sinal; SPLIT = needs_review (NUNCA
floora em split). O piso so age em unanime. O ruido do D1 (report-celula-base-D1-B1) era da SINTESE
GRANDE (clausula perturba a leitura global do flash); a tarefa estreita e binaria e nao sofre disso.

CONVENTION = VERBATIM da adjudicacao que acertou 76/76 com verify adversarial
(~/.claude/plans/celula-base-artifacts/adjudicate_celula.wf.js). NAO alargar (drift semantico = falha).
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from typing import List, Literal, Optional

from pydantic import BaseModel

from ...providers import create_provider
from ...providers.base import LLMResponse
from .._utils import MODEL_VARIANT_TEXT, seed_for

logger = logging.getLogger(__name__)

# gemini-3.5-flash: mesmo alvo do B1 (a tarefa estreita nao precisa mais). O engine injeta o model
# (SSOT); este default e so fallback pra callers nao-engine.
DEFAULT_MODEL = "gemini-3.5-flash"
_MAX_TOKENS = 8192
DEFAULT_N = 3

# CONVENTION VERBATIM de adjudicate_celula.wf.js (a SPEC 76/76). ASCII-only de proposito (imune ao
# canal CP1252 do Windows). Ao apertar, edite AQUI e re-valide contra adj_results.json (a referencia).
CONVENTION = """
Voce e um adjudicador de risco de SEGURO-GARANTIA JUDICIAL (Garantis). Um "merito" e um CLUSTER de
processos conexos sobre UMA divida/disputa de UM Tomador (o segurado da apolice). Julgue o risco
EMERGENTE de a apolice ser ACIONADA (Tomador perde e a garantia e executada), lendo o dossie INTEIRO.

BANDAS:
- Baixo: NENHUMA derrota de merito E ha SINAL POSITIVO de merito ao Tomador (decisao procedente/favoravel,
  divida sendo extinta/anulada/quitada, ou Tomador claramente vencendo a discussao).
- Medio: adverso-porem-suspenso -- derrota de merito de 1a inst com recurso de merito vivo, OU parcelamento
  com garantia, OU (CELULA-BASE, abaixo) divida adversa VIVA suspensa pela garantia sem sinal favoravel.
- Alto: derrota de merito contra o Tomador, SEM recurso de merito com efeito suspensivo, ainda nao transitada.
- Altissimo: derrota de merito TRANSITADA, OU recursos ESGOTADOS (STF/STJ/TST nao conheceram) + derrota, OU
  intimacao/decisao de pagamento pela seguradora.

VALENCIA (quem e o Tomador define "perder"):
- Tomador ATIVO (autor -- anulatoria, embargos, impugnacao): "improcedente"/"negado"/"nao provido" => PERDE
  => divida MANTIDA => ADVERSO. "procedente" => VENCE => favoravel.
- Tomador PASSIVO (reu/executado -- execucao fiscal/trabalhista contra ele): a execucao prosseguindo => ADVERSO;
  decisao que extingue/anula a divida a favor dele => favoravel.

*** CONVENCAO CELULA-BASE (decisao do Elton, 2026-07-11 -- a celula MAIS FREQUENTE do monitorado) ***
Garantia aceita / execucao SUSPENSA pela garantia so mantem BAIXO quando ha um SINAL POSITIVO de merito ao
Tomador. NA AUSENCIA de sinal favoravel -- quando a divida adversa segue VIVA (o credor/Fazenda a cobra, o
Tomador a discute mas ainda NAO a venceu no merito) e a exigibilidade esta apenas SUSPENSA pela garantia --
o piso e MEDIO, nao Baixo: divida viva adversa e EXPOSICAO LATENTE que a suspensao apenas DIFERE, nao elimina.
A mera suspensao (garantia aceita, EF suspensa, tutela, efeito suspensivo, recurso pendente) NAO basta para
Baixo. (Isto NAO eleva acima de Medio: se a derrota transitou/esgotou -> Alto/Altissimo.)
"""

_BAND = Literal["Baixo", "Medio", "Alto", "Altissimo"]


class CelulaClassifyOut(BaseModel):
    has_garantia_aceita: bool
    divida_adversa_viva: bool
    sinal_favoravel_merito: bool
    is_celula_base: bool
    elton_band: _BAND
    governing_citation: str
    reasoning: str


class CelulaVerifyOut(BaseModel):
    refuted: bool
    veredito_final: _BAND
    notes: str


class CelulaBaseClassifyRequest(BaseModel):
    merito_id: int
    dossier: str
    model: Optional[str] = None
    provider: Optional[str] = None
    n: int = DEFAULT_N
    run_verify: bool = True
    model_config = {"extra": "ignore"}


def _prompt(merito_id: int, dossier: str) -> str:
    return (
        f"{CONVENTION}\n\nDOSSIE do merito {merito_id}:\n\n```\n{dossier}\n```\n\n"
        f"Aplique a convencao (com atencao a CELULA-BASE) e classifique o merito {merito_id} como um todo. "
        f"Preencha os 3 flags estruturais (has_garantia_aceita, divida_adversa_viva, sinal_favoravel_merito), "
        f"derive is_celula_base = has_garantia_aceita AND divida_adversa_viva AND NOT sinal_favoravel_merito, "
        f"e a elton_band (celula-base -> Medio; transito/esgotamento -> Alto/Altissimo). Seja rigoroso com "
        f"valencia (quem e o Tomador). governing_citation = trecho curto do dossie que governa a exposicao. "
        f"Retorne o schema."
    )


def _verify_prompt(merito_id: int, dossier: str) -> str:
    # FAVORAVEL-ONLY (refinado da medicao 2026-07-11): o refutador da referencia tinha 2 gatilhos
    # (favoravel OU derrota-transitada->Alto/Altissimo). O 2o e CONTRAPRODUCENTE pra um piso que so faz
    # Baixo->Medio: refutar um merito que na verdade e Alto/Altissimo o DEIXA em Baixo (under MAIOR) em vez
    # de deixa-lo subir pra Medio (under menor) — no path B1-autoritativo o guard/DT nao re-escala. Entao o
    # verify AQUI so pergunta: ha um sinal FAVORAVEL REAL que faca o merito ser genuinamente BAIXO? (a classe
    # 680007 VALE: embargos procedente que o classify-only le como adverso). Merito MAIS grave NAO refuta —
    # continua sendo floored pra Medio (surety-safe; a escalada acima de Medio e problema de outro eixo).
    return (
        f"{CONVENTION}\n\nVERIFICADOR ADVERSARIAL (so o eixo FAVORAVEL). Um adjudicador classificou o merito "
        f"{merito_id} como CELULA-BASE (Baixo->Medio): divida adversa viva + garantia aceita + SEM sinal "
        f"favoravel. O piso so eleva Baixo->Medio (nunca abaixa e nunca passa de Medio). Leia o dossie e "
        f"responda UMA pergunta: existe um sinal FAVORAVEL de merito REAL e vivo (decisao procedente/favoravel "
        f"ao Tomador, divida sendo extinta/anulada/quitada, Tomador claramente vencendo a discussao de merito) "
        f"que torne o merito genuinamente BAIXO? Se sim, refuted=true (o piso NAO deve elevar). "
        f"⚠️ NAO refute so porque a derrota e PIOR (transitada/esgotada/Alto/Altissimo): um merito mais grave "
        f"continua corretamente elevado a Medio por este piso (a escalada acima de Medio e de outro eixo do "
        f"motor). refuted=true SOMENTE pra sinal FAVORAVEL genuino. Seja cetico mas honesto.\n\nDOSSIE do "
        f"merito {merito_id}:\n\n```\n{dossier}\n```\n\nRetorne o schema."
    )


def _usage(resp: LLMResponse, model: str, provider: str) -> dict:
    return {
        "input_tokens": resp.input_tokens or 0,
        "output_tokens": resp.output_tokens or 0,
        "total_tokens": (resp.input_tokens or 0) + (resp.output_tokens or 0),
        "cached_tokens": getattr(resp, "cached_tokens", 0) or 0,
        "cost_usd": (resp.metadata.get("cost_usd", 0.0) if resp.metadata else 0.0),
        "model": model,
        "provider": provider,
        "model_variant": MODEL_VARIANT_TEXT,
    }


async def classify_celula_base(
    request: CelulaBaseClassifyRequest | dict,
    model: Optional[str] = None,
    provider: str = "gemini",
) -> dict:
    """N=3 leituras estreitas (seeds VARIANDO) da celula-base. Unanime em is_celula_base sustenta o
    sinal; split = needs_review (o piso do L3 NUNCA floora em split -- surety-safe).

    Retorna {card:{celula_base: bool|None, unanimous, needs_review, votes_cb, votes_band, elton_band,
    governing_citation, reasoning, n_ok}, usage}. celula_base=None quando split OU votos insuficientes.
    Parse-fail de um voto so o descarta; so vira erro se TODOS os votos falharem (fail-clean no engine).
    """
    if isinstance(request, dict):
        request = CelulaBaseClassifyRequest(**request)
    model = model or request.model or DEFAULT_MODEL
    provider = request.provider or provider
    n = max(1, request.n)
    llm = create_provider(provider)
    prompt = _prompt(request.merito_id, request.dossier)

    votes: List[CelulaClassifyOut] = []
    usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "cached_tokens": 0,
             "cost_usd": 0.0,
             "model": model, "provider": provider, "model_variant": MODEL_VARIANT_TEXT}
    for k in range(n):
        # seed VARIA por k -> mede reproducibilidade da leitura estreita (temp0). seed_for=None
        # (flag off) => Gemini usa seed aleatorio, o que TAMBEM da N amostras independentes.
        seed = seed_for("celula_base_classifier", request.merito_id, k)
        try:
            resp: LLMResponse = await llm.agenerate(
                prompt=prompt, model=model, temperature=0.0,
                response_schema=CelulaClassifyOut, seed=seed, max_tokens=_MAX_TOKENS,
            )
            vote = CelulaClassifyOut(**json.loads(resp.text))
            votes.append(vote)
            u = _usage(resp, model, provider)
            for key in ("input_tokens", "output_tokens", "total_tokens", "cached_tokens"):
                usage[key] += u[key]
            usage["cost_usd"] = (usage["cost_usd"] or 0) + (u["cost_usd"] or 0)
        except Exception as e:  # noqa: BLE001 — 1 voto ruim so o descarta; TODOS ruins => card.error
            logger.warning(
                "CELULA_CLASSIFIER_VOTE_FAIL merito_id=%s k=%s: %r", request.merito_id, k, e)

    if not votes:
        logger.error("CELULA_CLASSIFIER_ALL_FAIL merito_id=%s — nenhum voto valido", request.merito_id)
        return {"card": {"error": "all_votes_failed"}, "usage": usage}

    votes_cb = [v.is_celula_base for v in votes]
    votes_band = [v.elton_band for v in votes]
    # UNANIME so quando os N pedidos deram voto E concordam (voto faltando != unanime -> needs_review).
    unanimous = len(votes) == n and len(set(votes_cb)) == 1
    celula_base = votes_cb[0] if unanimous else None
    # banda de exibicao/audit: moda (informativa; o piso so usa celula_base)
    elton_band = Counter(votes_band).most_common(1)[0][0]
    rep = votes[0]

    # VERIFY adversarial (mede refutou 680007 na referencia): so sobre movers (celula=True). O classify-only
    # N=3 (flash E sonnet) over-reacha na classe favoravel-que-parece-celula (680007 VALE: embargos procedente
    # lido como adverso); o refutador, prompted a ACHAR o favoravel, demote pra needs_review. Surety-safe: SO
    # rebaixa celula->needs_review, nunca promove. Falha do verify = conservador (mantem o sinal do classify).
    verify_refuted = None
    if celula_base is True and request.run_verify:
        try:
            vseed = seed_for("celula_base_verify", request.merito_id)
            vresp: LLMResponse = await llm.agenerate(
                prompt=_verify_prompt(request.merito_id, request.dossier), model=model,
                temperature=0.0, response_schema=CelulaVerifyOut, seed=vseed, max_tokens=4096,
            )
            verify = CelulaVerifyOut(**json.loads(vresp.text))
            verify_refuted = verify.refuted
            vu = _usage(vresp, model, provider)
            for key in ("input_tokens", "output_tokens", "total_tokens", "cached_tokens"):
                usage[key] += vu[key]
            usage["cost_usd"] = (usage["cost_usd"] or 0) + (vu["cost_usd"] or 0)
            if verify.refuted:
                celula_base = None  # refutado (sinal favoravel real) -> needs_review, NAO floora
                logger.info("CELULA_VERIFY_REFUTED merito_id=%s -> needs_review (%s)",
                            request.merito_id, verify.notes[:120])
        except Exception as e:  # noqa: BLE001 — verify best-effort; falha mantem o sinal do classify
            logger.warning("CELULA_VERIFY_FAIL merito_id=%s: %r", request.merito_id, e)

    needs_review = celula_base is None
    card = {
        "celula_base": celula_base,
        "unanimous": unanimous,
        "needs_review": needs_review,
        "verify_refuted": verify_refuted,
        "votes_cb": votes_cb,
        "votes_band": votes_band,
        "elton_band": elton_band,
        "governing_citation": rep.governing_citation,
        "reasoning": rep.reasoning,
        "n_ok": len(votes),
    }
    logger.info(
        "CELULA_CLASSIFIER merito_id=%s celula_base=%s unanimous=%s votes_cb=%s n_ok=%s",
        request.merito_id, celula_base, unanimous, votes_cb, len(votes))
    return {"card": card, "usage": usage}

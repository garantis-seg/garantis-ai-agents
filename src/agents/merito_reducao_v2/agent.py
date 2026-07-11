"""B1 — síntese/redução mérito-level de 1 passada (a semente = CONVENTION do oráculo).

1 call de síntese (banda) + 1 verify adversarial, ambos em gemini-3.5-flash. Determinismo
(gate-1) = temperature=0.0 + seed(ENGINE_LLM_SEED_ENABLED). Gate-2 (verify→needs_review) fica
no materializer do engine (lê `verify.band_supported`). O engine monta o dossiê (DB) e injeta
aqui como texto — este agent é stateless (não toca DB).

CONVENTION é VERBATIM do `oracle-artifacts/oracle_wf.js` (a redução que o gate-0 validou). Ao
apertar as regras, edite AQUI e re-valide na escada do gate-0.
"""
from __future__ import annotations

import json
import logging
from typing import List, Literal, Optional

from pydantic import BaseModel

from ...providers import create_provider
from ...providers.base import LLMResponse
from .._utils import MODEL_VARIANT_TEXT, seed_for

logger = logging.getLogger(__name__)

# gemini-3.5-flash: o alvo L2 de acurácia (não-lite; 3.5-flash-lite não existe). Gate-0
# provou que carrega o raciocínio da redução (iguala/supera opus). O engine injeta o model
# (SSOT ENGINE_LAYER3_V2_MODEL); este default é só fallback.
DEFAULT_MODEL = "gemini-3.5-flash"
# thinking dinâmico (SDK default p/ 3.5) — o provider só aplica thinking_budget em "2.5"; o
# gate-0 rodou com thinking-default e não truncou. max alto cobre thinking+JSON de méritos GIGANTES.
_MAX_TOKENS = 32768

# ── CONVENTION — semente = oracle_wf.js + R5 sharpening (2026-07-11, decisao Elton) ───────
# Rules 4/5 apertadas pra fechar os 2 danger-unders do E2E (680048 RE-sobrestado, 680136 agravo-
# interno residual): sobrestamento != exigibilidade; recurso residual/sobrestado apos merito ja
# rejeitado -> a derrota governa. + carve supersessao (parcelamento pos-transito -> Medio). Medido
# offline (report-R5-calibration-B1-2026-07-11.md): 680048->Alto, danger-unders eliminados, erro
# todo surety-safe. Ao apertar mais, edite AQUI e re-valide na escada do gate-0/r5cal.
CONVENTION = """
Voce e o passo de SINTESE/REDUCAO de um motor de risco de SEGURO-GARANTIA JUDICIAL (Garantis).
Um "merito" e um CLUSTER de processos conexos sobre UMA divida/disputa de UM Tomador (o segurado da apolice).
Sua tarefa: ler o dossie INTEIRO de TODOS os N processos JUNTOS e emitir UMA banda de risco para o merito
como um todo -- o risco EMERGENTE de a apolice ser ACIONADA (Tomador perde e a garantia e executada),
julgando o CONJUNTO, NAO cada processo isolado.

BANDAS (exposicao de acionamento da garantia):
- Baixo: sem derrota de merito; garantia aceita e divida em discussao / suspensa favoravelmente / Tomador vencendo.
- Medio: derrota de merito em 1a instancia COM recurso vivo pendente; OU parcelamento homologado com garantia mantida;
         OU adverso-porem-suspenso (execucao diferida).
- Alto: derrota de merito contra o Tomador que discute a divida, SEM recurso (ou recurso sem efeito suspensivo),
        ainda NAO transitada/executada.
- Altissimo: derrota de merito TRANSITADA em julgado; OU recursos ESGOTADOS (esgotamento consolidado -- ex. STF/STJ/TST
         nao conheceram/rejeitaram) + derrota de merito, MESMO sem intimacao de pagamento ("acionamento e questao de QUANDO,
         nao de SE"); OU intimacao para pagar / decisao determinando pagamento pela seguradora.

MATRIZ DAYCOVAL (situacao-processual -> banda; resumo do PDF oficial):
FISCAL:  Baixo = apolice aceita p/ embargos/anulatoria discutindo o debito, ou EF suspensa aguardando transito de anulatoria,
                 ou aguardando aceitacao. Medio = desfavoravel 1a inst COM recurso; parcelamento c/ garantia. Alto = desfavoravel
                 em embargos/anulatoria SEM recurso; descumprimento de parcelamento. Altissimo = desfavoravel TRANSITADO;
                 intimacao p/ pagamento pos-transito; pagamento pela seguradora.
CIVEL/TRAB: Baixo = apolice aceita p/ embargos/impugnacao, ou julgamento PROCEDENTE p/ Tomador, ou favoravel em 2a/ultima inst.
                 Medio = desfavoravel 1a inst COM recurso E efeito suspensivo; parcelamento c/ garantia. Alto = desfavoravel
                 em embargos/cumprimento/impugnacao COM prazo p/ recorrer (ou sem efeito suspensivo). Altissimo = desfavoravel
                 SEM recurso; intimacao p/ pagar condenacao; pagamento pela seguradora.

REGRAS DE LEITURA (aplique com rigor):
1. VALENCIA (quem e o Tomador define o que e "perder"):
   - Tomador ATIVO (autor/exequente -- ex. anulatoria, embargos, impugnacao): "improcedente"/"negado"/"nao provido"
     => Tomador PERDE => divida MANTIDA => ADVERSO. "procedente" => Tomador VENCE => favoravel.
   - Tomador PASSIVO (reu/executado -- ex. execucao fiscal/trabalhista contra ele): "procedente" (a favor do exequente)
     => ADVERSO; decisao que extingue/suspende a execucao a favor dele => favoravel.
   - Se a valencia do processo governante for INDEFINIDA, infira de classe+quem ajuizou, mas NAO inverta favoravel->adverso
     no chute (abster > inverter).
2. MERITO vs PROCEDIMENTAL: so decisao de MERITO (sentenca/acordao julgando procedente/improcedente/parcial a divida)
   cria "derrota". Interlocutoria, penhora, saneador, despacho, pericia, agravo-prejudicado (perda de objeto),
   extincao terminativa (sem resolucao de merito), declinio de competencia => NAO sao derrota de merito; nao fabrique derrota.
3. NULIDADE/ANULACAO: se uma sentenca de merito foi ANULADA/CASSADA em grau recursal (nulidade / ausencia de fundamentacao),
   o merito volta a INDECIDIDO -- nao trate a derrota anulada como final.
4. SUSPENSAO e causa-consciente: execucao suspensa por garantia-aceita / anulatoria-pendente / parcelamento-com-garantia
   DIFERE o risco (nao o eleva sozinha). MAS um TRANSITO adverso em QUALQUER processo do cluster PREVALECE sobre uma
   suspensao PASSIVA (garantia aceita / sobrestamento) anterior.
   ATENCAO ao que conta como efeito suspensivo: o que REBAIXA o risco e o efeito suspensivo da EXIGIBILIDADE (embargos
   recebidos no efeito suspensivo, tutela cautelar ativa). O SOBRESTAMENTO de um recurso (RE/REsp sobrestado por
   repercussao geral / Tema STF-STJ) suspende o PROCESSAMENTO do recurso, NAO a exigibilidade -- a execucao prossegue,
   entao NAO rebaixa o risco por si so.
   EXCECAO (supersessao / recencia): um PARCELAMENTO homologado com garantia mantida que e POSTERIOR a uma derrota
   transitada NAO e mera suspensao passiva -- e um NOVO ato dispositivo (o Tomador esta PAGANDO/negociou) que, sendo o
   ULTIMO ato do cluster, SUPERSEDE a derrota transitada => Medio, nao Altissimo. (Regra geral: entre atos dispositivos
   que se contradizem no tempo, o MAIS RECENTE governa.)
5. ESGOTAMENTO e RECURSO RESIDUAL (o divisor Medio/Alto/Altissimo):
   - Recursos de MERITO esgotados (STF/STJ/TST rejeitaram/nao conheceram) + derrota de merito = Altissimo, mesmo sem
     intimacao de pagamento.
   - Recurso ainda VIVO so mantem Medio/Alto quando e recurso de MERITO substantivo genuinamente pendente (apelacao/REsp/RE
     ainda NAO julgado) COM efeito suspensivo real da exigibilidade.
   - NAO segura em Medio (a derrota de merito CONFIRMADA governa -> Alto, ou Altissimo se transitada/esgotada):
     (a) recurso RESIDUAL/procedimental (agravo interno, embargos de declaracao) interposto DEPOIS de o merito ja ter
         sido decidido adverso e os recursos de merito (apelacao/REsp/RE) ja rejeitados/nao conhecidos;
     (b) recurso SOBRESTADO por repercussao geral sobre derrota de merito JA CONFIRMADA em 2a instancia.
6. REDUCAO (o nucleo da sua tarefa): a banda do merito e governada pelo processo/decisao que dirige a EXPOSICAO -- em geral
   o desfecho de merito da PROPRIA divida, nao uma decisao lateral favoravel. NAO tome o max ingenuo dos cards por-processo,
   e NAO deixe uma interlocutoria/decisao favoravel em um processo ESCONDER uma derrota de merito em outro. Identifique a
   DECISAO GOVERNANTE do cluster e classifique por ela.
7. DOC-PRESENCA / abster>inverter: se o dossie NAO tem ruling de merito ingerido para o processo governante, voce NAO PODE
   saber o desfecho -- marque decisive_doc_present=false e julgue conservador nos sinais disponiveis (garantia aceita +
   exposicao + postura processual); nao invente derrota.

Voce esta CEGO ao gabarito humano e a qualquer banda previa do motor. Julgue so pelo dossie e por esta convencao.
"""

_BAND = Literal["Baixo", "Medio", "Alto", "Altissimo"]


class BandOut(BaseModel):
    band: _BAND
    governing_process: str
    decisive_doc_present: bool
    reasoning: str
    citations: List[str]


class VerifyOut(BaseModel):
    citations_all_found: bool
    decisive_ruling_in_dossier: bool
    band_supported: bool
    notes: str


class MeritoReducaoV2Request(BaseModel):
    merito_id: int
    dossier: str
    model: Optional[str] = None
    provider: Optional[str] = None
    run_verify: bool = True
    model_config = {"extra": "ignore"}


def _oracle_prompt(merito_id: int, dossier: str) -> str:
    return (
        f"{CONVENTION}\n\nDOSSIE do merito {merito_id}:\n\n```\n{dossier}\n```\n\n"
        f"Emita a banda do MERITO {merito_id} como um todo, seguindo a convencao e as 7 regras. "
        "Retorne o schema: band, governing_process, decisive_doc_present, reasoning (<=120 palavras), "
        "citations (2-4 trechos curtos citados do dossie)."
    )


def _verify_prompt(merito_id: int, band: BandOut, dossier: str) -> str:
    return (
        "Voce e um VERIFICADOR ADVERSARIAL. NAO julgue o risco; verifique a honestidade do voto abaixo "
        f"contra o dossie.\n\nDOSSIE:\n```\n{dossier}\n```\n\n"
        f"Voto do oraculo (merito {merito_id}): band={band.band} gov={band.governing_process} "
        f"doc_present={band.decisive_doc_present} | {band.reasoning}\n\nLendo o dossie:\n"
        "- citations_all_found: as citacoes do voto realmente aparecem no texto do dossie?\n"
        "- decisive_ruling_in_dossier: existe de fato uma sentenca/acordao de MERITO do processo governante "
        "citado (nao interlocutoria/procedimental)?\n"
        "- band_supported: a banda e sustentavel pelo dossie sob a convencao, ou foi FABRICADA (derrota inventada "
        "de peca procedimental, ou inversao de valencia)?\nSeja cetico: default a false se houver duvida. Retorne o schema."
    )


def _usage(resp: LLMResponse, model: str, provider: str) -> dict:
    return {
        "input_tokens": resp.input_tokens or 0,
        "output_tokens": resp.output_tokens or 0,
        "total_tokens": (resp.input_tokens or 0) + (resp.output_tokens or 0),
        "cost_usd": (resp.metadata.get("cost_usd", 0.0) if resp.metadata else 0.0),
        "model": model,
        "provider": provider,
        "model_variant": MODEL_VARIANT_TEXT,
    }


async def classify_merito_reducao_v2(
    request: MeritoReducaoV2Request | dict,
    model: Optional[str] = None,
    provider: str = "gemini",
) -> dict:
    """Retorna {card: {band,governing_process,decisive_doc_present,reasoning,citations,verify}, usage, raw_response}
    ou {card:{error:...}} em parse-fail (o materializer trata como fail-clean → mantém o L3 legado)."""
    if isinstance(request, dict):
        request = MeritoReducaoV2Request(**request)
    model = model or request.model or DEFAULT_MODEL
    provider = request.provider or provider
    llm = create_provider(provider)

    prompt = _oracle_prompt(request.merito_id, request.dossier)
    seed = seed_for("merito_reducao_v2", request.merito_id, prompt)  # gate-1 determinismo (gated)
    resp: LLMResponse = await llm.agenerate(
        prompt=prompt, model=model, temperature=0.0,
        response_schema=BandOut, seed=seed, max_tokens=_MAX_TOKENS,
    )
    try:
        band = BandOut(**json.loads(resp.text))
    except Exception as e:  # noqa: BLE001 — parse-fail vira fail-clean no engine
        logger.error(
            "MERITO_REDUCAO_V2_PARSE_FAIL merito_id=%s: %r | raw_head=%r",
            request.merito_id, e, (resp.text or "")[:200],
        )
        return {"card": {"error": repr(e)}, "raw_response": resp.text,
                "usage": _usage(resp, model, provider)}

    usage = _usage(resp, model, provider)
    verify = None
    if request.run_verify:
        vseed = seed_for("merito_reducao_v2_verify", request.merito_id, prompt)
        try:
            vresp: LLMResponse = await llm.agenerate(
                prompt=_verify_prompt(request.merito_id, band, request.dossier),
                model=model, temperature=0.0, response_schema=VerifyOut,
                seed=vseed, max_tokens=8192,
            )
            verify = VerifyOut(**json.loads(vresp.text)).model_dump()
            vusage = _usage(vresp, model, provider)
            usage["input_tokens"] += vusage["input_tokens"]
            usage["output_tokens"] += vusage["output_tokens"]
            usage["total_tokens"] += vusage["total_tokens"]
            usage["cost_usd"] = (usage["cost_usd"] or 0) + (vusage["cost_usd"] or 0)
        except Exception as e:  # noqa: BLE001 — verify é best-effort; band-supported=None → gate-2 fecha conservador
            logger.warning("MERITO_REDUCAO_V2_VERIFY_FAIL merito_id=%s: %r", request.merito_id, e)

    card = band.model_dump()
    card["verify"] = verify
    return {"card": card, "raw_response": resp.text, "usage": usage}

"""AUDITOR DE FICHA (S6), versao 3: o auditor que abre os autos para refutar.

Decisao do Alfredo de 23/10/2026: "nucleo obrigatorio + indice navegavel; o
auditor vira v3 como agente". Mesmo endpoint (`POST /ficha/auditar`). O v3 liga
quando o request traz `nucleo`, `indice_navegavel` ou `trilha_leitura`. O v2
continua igual para o request antigo.

Duas fases, no molde do redator v5 (`ficha_writer/agent_v5.py`):

- Fase A (navegacao): sem schema. O auditor abre os documentos que o redator
  citou na trilha (e outros) com as ferramentas do investigador. Budget: 20
  chamadas por ficha e 5 por documento, com circuit breaker.
- Fase B (veredito): JSON. A saida do v2, com `prova` ou `sem_prova_no_doc` em
  cada item dos baldes e `fatos_conferidos`. O codigo valida e pede 1 correcao
  (as mesmas `MAX_RODADAS` do v2).

Regras duras (no codigo):

1. Cada item dos baldes traz `prova` {doc_id, pagina, trecho} ou
   `sem_prova_no_doc: true` (schema `_ComProva`).
2. A prova cita um documento do nucleo ou um documento do indice que o auditor
   leu na fase A. Com o texto disponivel, o trecho esta no documento.
3. Um fato "contradito" sem prova de documento NAO entra no balde 1. O codigo
   move o item ao balde 2 com grau `media`.
4. Todo slot da trilha do redator tem um item em `fatos_conferidos`. Silencio
   nao aprova. Todo `confere=false` tem item no balde 1 ou 2 do mesmo campo.
5. O v3 nunca recebe gabarito (Livro §10.2): o schema recusa o request.

FAIL-SAFE, como no v2: falha vira `success=false`, `aprovado=false` e
`auditor_enabled=false` ("nao auditada").
"""

import logging
from pathlib import Path
from typing import Any, Callable, Optional

from garantis_shared.llm_models import model_for
from pydantic import ValidationError

from ...providers import create_provider
from ...utils.llm_json import parse_llm_json
from .._utils.llm_seed import seed_for
from .._utils.prompt_identity import versao_com_identidade
from ..ficha_writer.ferramentas import Autos, BudgetNavegacao, custo_da_resposta, navegar
from ..ficha_writer.schemas import Nucleo
from .agent import (
    MAX_RODADAS,
    _ancorar,
    _falha,
    _pendencias,
    calcular_veredito,
    erros_de_alertas,
)
from .checklist import SO_BALDE_2
from .prompts import build_prompt_de_correcao
from .prompts_v3 import PROMPT_VERSION, build_prompt_navegacao_v3, build_prompt_v3
from .schemas import (
    AuditarFichaRequest,
    AuditarFichaResponse,
    ItemBalde1V3,
    ItemBalde2V3,
    SaidaAuditorV3,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = model_for("ficha_auditoria_texto")

#: Budget da fase A (pedido de 23/10/2026).
BUDGET_POR_FICHA = 20
BUDGET_POR_DOC = 5

#: Texto do balde 2 quando o codigo move um item sem prova (regra 3).
EVIDENCIA_SEM_PROVA = "(o auditor nao achou trecho de documento que contradiga o texto)"

_AQUI = Path(__file__).resolve().parent


def prompt_version() -> str:
    """`auditor_ficha_v3+<hash>`. O hash muda com o prompt v3, o prompt v2 ou o schema."""
    return versao_com_identidade(
        PROMPT_VERSION, str(_AQUI / "prompts_v3.py"), str(_AQUI / "prompts.py"),
        str(_AQUI / "schemas.py"),
    )


# ── Validacao ──────────────────────────────────────────────────────────────


def validar_saida_v3(
    parsed: Any, request: AuditarFichaRequest, autos: Autos,
) -> tuple[Optional[SaidaAuditorV3], list[dict[str, Any]]]:
    """Valida o JSON do modelo. Devolve `(saida, erros)` no formato
    `{campo, erro, valor_anterior}`. Lista vazia = saida valida."""
    if not isinstance(parsed, dict):
        return None, [{
            "campo": "_raiz", "erro": "a resposta tem de ser um objeto JSON",
            "valor_anterior": type(parsed).__name__,
        }]
    try:
        saida = SaidaAuditorV3.model_validate(parsed)
    except ValidationError as e:
        return None, [{
            "campo": ".".join(str(x) for x in err.get("loc", ())) or "_raiz",
            "erro": err.get("msg", "invalido"), "valor_anterior": err.get("input"),
        } for err in e.errors(include_url=False)]

    erros = erros_de_alertas(saida, request)
    if saida.divergencias_gabarito:
        erros.append({
            "campo": "divergencias_gabarito",
            "erro": "nao ha gabarito no v3: a lista tem de ser vazia",
            "valor_anterior": len(saida.divergencias_gabarito),
        })

    # Regra 2: a prova cita documento existente, lido, com o trecho literal.
    for balde, itens in (("balde1", saida.balde1), ("balde2", saida.balde2)):
        for i, it in enumerate(itens):
            if it.prova is None:
                continue
            erro = autos.conferir_citacao(it.prova.doc_id, [it.prova.pagina], it.prova.trecho)
            if erro:
                erros.append({"campo": f"{balde}[{i}].prova", "erro": erro,
                              "valor_anterior": it.prova.model_dump()})

    # Regra 4: todo slot da trilha conferido; todo `confere=false` acusado.
    for i, f in enumerate(saida.fatos_conferidos):
        if not autos.existe(f.doc_id):
            erros.append({"campo": f"fatos_conferidos[{i}].doc_id",
                          "erro": "doc_id fora do nucleo e do indice",
                          "valor_anterior": f.doc_id})
    conferidos = {f.slot.strip() for f in saida.fatos_conferidos}
    for slot in dict.fromkeys(t.slot for t in request.trilha_leitura or []):
        if slot not in conferidos:
            erros.append({"campo": "fatos_conferidos",
                          "erro": f"o slot {slot} da trilha nao foi conferido",
                          "valor_anterior": None})
    acusados = {i.campo.strip() for i in saida.balde1} | {i.campo.strip() for i in saida.balde2}
    for f in saida.fatos_conferidos:
        if not f.confere and f.slot.strip() not in acusados:
            erros.append({
                "campo": "fatos_conferidos",
                "erro": (f"{f.slot}: confere=false sem item no balde 1 ou no balde 2 "
                         "do mesmo campo"),
                "valor_anterior": f.model_dump(),
            })
    return (saida if not erros else None), erros


def normalizar_baldes_v3(
    saida: SaidaAuditorV3,
) -> tuple[list[ItemBalde1V3], list[ItemBalde2V3]]:
    """As regras do v2 (item vazio sai, ancora, "SO balde 2") mais a regra 3."""
    b1: list[ItemBalde1V3] = []
    b2: list[ItemBalde2V3] = list(saida.balde2)
    for it in saida.balde1:
        campo, motivo = it.campo.strip(), it.motivo.strip()
        if not campo or not motivo:
            continue
        regra = it.regra.strip()
        if it.sem_prova_no_doc:
            # Regra 3 (23/10/2026): contradito sem prova de documento -> balde 2, media.
            b2.append(ItemBalde2V3(
                campo=campo, pendencia=motivo, grau="media",
                evidencia=EVIDENCIA_SEM_PROVA,
                recomendacao=("Conferir nos autos. O codigo moveu o item do balde 1 "
                              f"para o balde 2: o item {regra or 'sem regra'} nao tem "
                              "prova de documento."),
                prova=None, sem_prova_no_doc=True,
            ))
            continue
        if regra in SO_BALDE_2:
            b2.append(ItemBalde2V3(
                campo=campo, pendencia=motivo, grau="media",
                evidencia=it.correcao_sugerida or "(o modelo pos o item no balde 1)",
                recomendacao=f"Conferir o item {regra} do checklist. O codigo moveu "
                             "o item do balde 1 para o balde 2.",
                prova=it.prova, sem_prova_no_doc=False,
            ))
            continue
        b1.append(it.model_copy(update={
            "campo": campo, "motivo": motivo, "regra": _ancorar(regra),
            "correcao_sugerida": it.correcao_sugerida.strip(),
        }))
    return b1, b2


# ── Ponto de entrada ───────────────────────────────────────────────────────


async def auditar_ficha_v3(
    request: AuditarFichaRequest,
    provider: str,
    model: Optional[str] = None,
    leitor_perguntar: Optional[Callable] = None,
    leitor_resumir: Optional[Callable] = None,
) -> AuditarFichaResponse:
    """Audita a ficha lendo os autos. Nunca levanta: toda falha vira `success=false`."""
    model = model or DEFAULT_MODEL
    pv = prompt_version()

    def falha(erro: str, **kw: Any) -> AuditarFichaResponse:
        return _falha(erro, kw.pop("modelo", model), **kw).model_copy(
            update={"prompt_version": pv})

    nucleo = request.nucleo or Nucleo()
    if not request.ficha:
        return falha("nenhuma ficha para auditar")
    if not request.dossie.strip() and not nucleo.documentos():
        return falha("dossie vazio e nucleo sem documento: nao ha contra o que conferir")

    autos = Autos(nucleo, request.indice_navegavel or [])
    nucleo_llm = autos.nucleo_para_llm()
    indice_llm = autos.indice_para_llm()
    chave_seed = str((request.esqueleto or {}).get("processo_id")
                     or (request.ficha or {}).get("processo_id") or "")
    llm = create_provider(provider)

    # ── Fase A — navegacao ─────────────────────────────────────────────────
    budget = BudgetNavegacao(max_por_ficha=BUDGET_POR_FICHA, max_por_doc=BUDGET_POR_DOC)
    nav = await navegar(
        llm=llm, model=model, autos=autos, budget=budget,
        prompt_de_decisao=lambda achados, menu, restante, por_doc: build_prompt_navegacao_v3(
            request, nucleo=nucleo_llm, indice=indice_llm, achados=achados, menu=menu,
            budget_restante=restante, budget_por_doc=por_doc,
        ),
        seed=lambda turno: seed_for("auditor_ficha_v3", chave_seed, "A", turno),
        leitor_perguntar=leitor_perguntar, leitor_resumir=leitor_resumir,
        rotulo="AUDITOR_FICHA_V3",
    )
    cost_usd = nav.custo_usd
    nav_info = {
        "documentos_lidos": sorted(autos.lidos), "chamadas_ferramenta": budget.chamadas,
        "budget_esgotado": nav.budget_esgotado,
    }

    # ── Fase B — veredito ──────────────────────────────────────────────────
    prompt_base = build_prompt_v3(request, nucleo=nucleo_llm, indice=indice_llm,
                                  achados=nav.achados)
    prompt = prompt_base
    used_model = model
    erros: list[dict[str, Any]] = []
    saida: Optional[SaidaAuditorV3] = None
    for rodada in range(1, MAX_RODADAS + 1):
        resp = await llm.agenerate(
            prompt=prompt, model=model, temperature=0.0,
            response_mime_type="application/json", max_tokens=16384,
            seed=seed_for("auditor_ficha_v3", chave_seed, "B", rodada),
        )
        raw = resp.text or ""
        used_model = resp.model or model
        cost_usd += custo_da_resposta(resp)
        try:
            parsed = parse_llm_json(raw)
        except Exception as e:  # noqa: BLE001
            logger.warning("AUDITOR_FICHA_V3_PARSE_FAIL rodada=%d: %r", rodada, e)
            erros = [{"campo": "_raiz", "erro": f"JSON invalido: {e}", "valor_anterior": raw[:500]}]
        else:
            saida, erros = validar_saida_v3(parsed, request, autos)
        if saida is not None:
            break
        logger.info("AUDITOR_FICHA_V3_422 rodada=%d erros=%s", rodada, erros)
        if rodada < MAX_RODADAS:
            prompt = build_prompt_de_correcao(prompt_base, raw, erros)
    else:
        r = falha(f"422: saida do modelo invalida depois de {MAX_RODADAS} rodadas",
                  modelo=used_model, cost_usd=cost_usd, rodadas=MAX_RODADAS,
                  erros_validacao=erros)
        return r.model_copy(update=nav_info)

    balde1, balde2 = normalizar_baldes_v3(saida)
    veredito = calcular_veredito(balde1, balde2)
    if saida.veredito and saida.veredito != veredito:
        logger.info("AUDITOR_FICHA_V3_VEREDITO_DIVERGENTE modelo=%s codigo=%s",
                    saida.veredito, veredito)
    logger.info("AUDITOR_FICHA_V3_OK veredito=%s balde1=%d balde2=%d chamadas=%d",
                veredito, len(balde1), len(balde2), budget.chamadas)
    return AuditarFichaResponse(
        success=True,
        veredito=veredito,
        balde1=balde1,
        balde2=balde2,
        nao_confirmado=[s for s in saida.nao_confirmado if s.strip()],
        alertas_respondidos=saida.alertas_respondidos,
        divergencias_gabarito=[],
        aprovado=veredito != "retida",
        auditor_enabled=True,
        modelo=used_model,
        reprovacoes=[{"campo": i.campo, "motivo": i.motivo, "regra": i.regra} for i in balde1],
        pendencias=_pendencias(veredito, balde2),
        rodadas=rodada,
        prompt_version=pv,
        model=used_model,
        cost_usd=cost_usd,
        error=None,
        fatos_conferidos=saida.fatos_conferidos,
        **nav_info,
    )


__all__ = [
    "BUDGET_POR_DOC",
    "BUDGET_POR_FICHA",
    "DEFAULT_MODEL",
    "auditar_ficha_v3",
    "normalizar_baldes_v3",
    "prompt_version",
    "validar_saida_v3",
]

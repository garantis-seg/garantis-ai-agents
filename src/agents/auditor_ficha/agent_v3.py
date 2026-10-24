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
6. (23/10/2026) Contradicao com o esqueleto e balde 1, nunca balde 2. O item com
   `contradiz_esqueleto=true`, ou cujo motivo cita um fato do esqueleto (a palavra
   "esqueleto", uma etapa com o status, uma data do esqueleto), fica no balde 1 ou
   vai ao balde 1. O esqueleto e a prova. Vale so para slot de texto: discordar
   do proprio esqueleto (campo `pipeline`, `valor`) continua balde 2 (T-01).
7. (23/10/2026) D-FONTE: antes do LLM, o codigo aplica as regras 11 e 12 do
   redator (`ficha_writer.validacao.FontesDeFato`) a cada slot de texto da ficha.
   Data, numero ou esgotamento sem fonte vira item do balde 1 com
   `regra="D-FONTE"`. As fontes: o nucleo, todo documento legivel do indice, o
   esqueleto, os fatos do codigo na ficha, o indice e os alertas.
8. (23/10/2026) `fatos_conferidos` sai sempre. Sem trilha do redator, o auditor
   confere cada slot de merito, de decisao, de infracao e de bullet da ficha.

Rodada real de 23/10/2026 (IRB 1481420, rev 00413): o redator inventou a data
01/09/2026 e o esgotamento. O auditor viu a contradicao com o esqueleto, pos o
item no balde 2 (sem prova de documento), e a ficha saiu aprovada. As regras 6 e
7 fecham esse caminho.

Determinismo maximo (plano 1.2, 23/10/2026), o mesmo do redator v5: antes de
reprovar uma prova, o codigo conserta ou verifica (`_reparar_provas` e
`Autos.verificar`):

- `prova.trecho` longo: o codigo corta em 300 caracteres, no fim de palavra.
- `prova.pagina` ausente: para documento do nucleo, o codigo usa 1 (o nucleo nao
  tem pagina, e o codigo confere o texto inteiro). Para documento do indice, o
  codigo acha a pagina do trecho. Pagina errada: o codigo corrige.
- Documento que a fase A nao leu: o codigo abre o documento (ate 5 por ficha) e
  confere o trecho. Sem sucesso, o erro da a lista dos documentos citaveis.

FAIL-SAFE, como no v2: falha vira `success=false`, `aprovado=false` e
`auditor_enabled=false` ("nao auditada").
"""

import logging
import re
from pathlib import Path
from typing import Any, Callable, Optional

from garantis_shared.llm_models import model_for
from pydantic import ValidationError

from ...providers import create_provider
from ...utils.llm_json import parse_llm_json
from .._utils.llm_seed import seed_for
from .._utils.prompt_identity import versao_com_identidade
from ..ficha_writer.ferramentas import (
    Autos,
    BudgetNavegacao,
    cortar_trecho,
    custo_da_resposta,
    navegar,
)
from ..ficha_writer.prompts_v5 import exige_trilha
from ..ficha_writer.schemas import Nucleo
from ..ficha_writer.validacao import (
    FontesDeFato,
    datas_no_texto,
    sem_acento,
    sem_slots_de_texto,
    slots_de_texto,
)
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
    MAX_CORRECAO_SUGERIDA,
    MAX_TRECHO_PROVA,
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

#: A regra do item que o proprio codigo acha (regra 7, 23/10/2026).
REGRA_D_FONTE = "D-FONTE"
#: A regra do item do balde 2 que o codigo move ao balde 1 (regra 6): T-01 diz "a
#: prosa segue o esqueleto (balde 1)".
REGRA_ESQUELETO = "T-01"
_CORRECAO_D_FONTE = ("Tire o fato sem fonte ou troque o fato por um que esta nas fontes "
                     "(nucleo, documentos, esqueleto). Siga o pipeline do esqueleto.")

#: Slot de texto da ficha (o campo do item). Regra 6.
_RE_SLOT_TEXTO = re.compile(
    r"^(?:descricao_infracao|valor\.descricao|processo_administrativo\.resumo|"
    r"ultima_decisao\.texto|ultima_ocorrencia\.texto|bullets\[\d+\]|merito\.\w+|"
    r"observacao|divida_ativa\.detalhe)$")
#: Palavra de status no motivo: com o nome de uma etapa, o motivo cita o esqueleto.
_RE_STATUS = re.compile(r"em[ _]andamento|concluid|futur|pendente|\bstatus\b|etapa[ _]atual")

_AQUI = Path(__file__).resolve().parent


def prompt_version() -> str:
    """`auditor_ficha_v3+<hash>`. O hash muda com o prompt v3, o prompt v2 ou o schema."""
    return versao_com_identidade(
        PROMPT_VERSION, str(_AQUI / "prompts_v3.py"), str(_AQUI / "prompts.py"),
        str(_AQUI / "schemas.py"),
    )


# ── Fontes e esqueleto (regras 6, 7 e 8, 23/10/2026) ──────────────────────


def _pipeline(request: AuditarFichaRequest) -> list[Any]:
    return list((request.esqueleto or {}).get("pipeline")
                or (request.ficha or {}).get("pipeline") or [])


def fontes_do_auditor(request: AuditarFichaRequest, autos: Autos) -> FontesDeFato:
    """As fontes da regra 7: as mesmas do redator, com todo documento legivel."""
    nucleo = request.nucleo or Nucleo()
    sem_texto = {"__all__": {"texto"}}
    nucleo_dados = nucleo.model_dump(mode="json", exclude={
        "docs": sem_texto, "acordaos": sem_texto,
        "peticao_inicial": {"texto"}, "ultima_decisao": {"texto"},
    })
    indice = [d.model_dump(mode="json", exclude={"documento_indexado"})
              for d in (request.indice_navegavel or [])]
    return FontesDeFato.montar(
        textos_docs=autos.textos_de_fonte(todos_os_legiveis=True),
        estruturados=[
            sem_slots_de_texto(request.esqueleto or {}),
            sem_slots_de_texto(request.ficha or {}),
            [a.model_dump() for a in request.alertas], nucleo_dados, indice,
        ],
        pipeline=_pipeline(request),
    )


def achados_d_fonte(request: AuditarFichaRequest, fontes: FontesDeFato) -> list[ItemBalde1V3]:
    """Regra 7: cada slot de texto com data, numero ou esgotamento sem fonte."""
    itens: list[ItemBalde1V3] = []
    for slot, texto in slots_de_texto(request.ficha or {}).items():
        for e in fontes.erros_do_slot(slot, texto):
            itens.append(ItemBalde1V3(
                campo=slot, motivo=e.erro, regra=REGRA_D_FONTE,
                correcao_sugerida=_CORRECAO_D_FONTE, prova=None, sem_prova_no_doc=True,
            ))
    if itens:
        logger.info("AUDITOR_FICHA_V3_D_FONTE %s", [i.campo for i in itens])
    return itens


def contradiz_esqueleto(campo: str, texto: str, marcado: bool,
                        esqueleto: dict[str, Any], pipeline: list[Any]) -> bool:
    """Regra 6: o item acusa um slot de texto que contradiz o esqueleto?

    Sim quando o campo e um slot de texto e: o auditor marcou `contradiz_esqueleto`,
    ou o texto do item diz "esqueleto", ou cita uma etapa do pipeline com um status,
    ou cita uma data do esqueleto.
    """
    if not _RE_SLOT_TEXTO.match(campo.strip()):
        if marcado:
            logger.info("AUDITOR_FICHA_V3_ESQUELETO_FORA_DE_SLOT campo=%s", campo)
        return False
    if marcado:
        return True
    t = sem_acento(texto)
    if "esqueleto" in t:
        return True
    etapas = {sem_acento(e.get("etapa") if isinstance(e, dict) else "") for e in pipeline}
    if any(len(e) >= 3 and e in t for e in etapas) and _RE_STATUS.search(t):
        return True
    datas_esq = {k for _t, k in datas_no_texto(str(sem_slots_de_texto(esqueleto or {})))}
    return any(k in datas_esq for _t, k in datas_no_texto(texto))


def slots_a_conferir(request: AuditarFichaRequest, autos: Autos) -> list[str]:
    """Regra 8: os slots que `fatos_conferidos` cobre. Sem trilha, os da ficha."""
    trilha = list(dict.fromkeys(t.slot for t in request.trilha_leitura or []))
    if trilha:
        return trilha
    if not (autos.textos_nucleo or autos.legiveis):
        return []
    return [s for s, t in slots_de_texto(request.ficha or {}).items()
            if exige_trilha(s) and t.strip()]


# ── Validacao ──────────────────────────────────────────────────────────────


def _pagina_valida(p: Any) -> bool:
    return isinstance(p, int) and not isinstance(p, bool) and p >= 1


def _reparar_provas(parsed: Any, autos: Autos) -> Any:
    """Conserta a forma das provas antes do schema (23/10/2026). Nao reprova nada.

    - `trecho` longo: corte em `MAX_TRECHO_PROVA`, no fim de palavra.
    - `pagina` ausente ou invalida: 1 no documento do nucleo. No documento do
      indice legivel, a pagina em que o codigo acha o trecho.
    """
    if not isinstance(parsed, dict):
        return parsed
    out = dict(parsed)
    for balde in ("balde1", "balde2"):
        itens = out.get(balde)
        if not isinstance(itens, list):
            continue
        novos = []
        for it in itens:
            prova = it.get("prova") if isinstance(it, dict) else None
            if not isinstance(prova, dict):
                novos.append(it)
                continue
            prova = dict(prova)
            if "trecho" in prova:
                prova["trecho"] = cortar_trecho(prova["trecho"], MAX_TRECHO_PROVA)
            pagina = prova.get("pagina")
            if isinstance(pagina, str) and pagina.strip().isdigit():
                pagina = prova["pagina"] = int(pagina)
            if not _pagina_valida(pagina):
                doc_id = str(prova.get("doc_id") or "")
                if doc_id in autos.textos_nucleo:
                    prova["pagina"] = 1
                elif doc_id in autos.legiveis and isinstance(prova.get("trecho"), str):
                    conf = autos.verificar(doc_id, [], prova["trecho"])
                    if conf.erro is None and conf.paginas:
                        prova["pagina"] = conf.paginas[0]
            novos.append({**it, "prova": prova})
        out[balde] = novos
    return out


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
    parsed = _reparar_provas(parsed, autos)
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

    # Regra 2: a prova cita documento existente, lido, com o trecho no texto
    # (`trecho_confere`: literal, prefixo ou similar; 23/10/2026).
    for balde, itens in (("balde1", saida.balde1), ("balde2", saida.balde2)):
        for i, it in enumerate(itens):
            if it.prova is None:
                continue
            no_nucleo = it.prova.doc_id in autos.textos_nucleo
            conf = autos.verificar(it.prova.doc_id, [] if no_nucleo else [it.prova.pagina],
                                   it.prova.trecho)
            if conf.erro:
                erros.append({"campo": f"{balde}[{i}].prova", "erro": conf.erro,
                              "valor_anterior": it.prova.model_dump()})
                continue
            if conf.paginas_corrigidas and conf.paginas:
                it.prova = it.prova.model_copy(update={"pagina": conf.paginas[0]})
            if conf.verificado_pelo_codigo:
                logger.info("AUDITOR_FICHA_V3_VERIFICADO_PELO_CODIGO %s[%d] doc=%s",
                            balde, i, it.prova.doc_id)
            if conf.metodo and conf.metodo != "literal":
                # 23/10/2026: o trecho casou por prefixo ou similar (`trecho_confere`).
                logger.info("AUDITOR_FICHA_V3_TRECHO_APROXIMADO %s[%d] doc=%s metodo=%s",
                            balde, i, it.prova.doc_id, conf.metodo)

    # Regra 4: todo slot da trilha conferido; todo `confere=false` acusado.
    for i, f in enumerate(saida.fatos_conferidos):
        if not autos.existe(f.doc_id):
            erros.append({"campo": f"fatos_conferidos[{i}].doc_id",
                          "erro": "doc_id fora do nucleo e do indice",
                          "valor_anterior": f.doc_id})
    conferidos = {f.slot.strip() for f in saida.fatos_conferidos}
    sem_trilha = not request.trilha_leitura
    for slot in slots_a_conferir(request, autos):
        if slot not in conferidos:
            origem = "da ficha (sem trilha do redator)" if sem_trilha else "da trilha"
            erros.append({"campo": "fatos_conferidos",
                          "erro": f"o slot {slot} {origem} nao foi conferido",
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
    esqueleto: Optional[dict[str, Any]] = None,
    pipeline: Optional[list[Any]] = None,
) -> tuple[list[ItemBalde1V3], list[ItemBalde2V3]]:
    """As regras do v2 (item vazio sai, ancora, "SO balde 2") mais as regras 3 e 6.

    A regra 6 vem antes da 3: a contradicao com o esqueleto fica no balde 1 mesmo
    sem prova de documento, e um item do balde 2 que contradiz o esqueleto vai ao
    balde 1.
    """
    esqueleto, pipeline = esqueleto or {}, list(pipeline or [])
    b1: list[ItemBalde1V3] = []
    b2: list[ItemBalde2V3] = []
    for it in saida.balde2:
        campo = it.campo.strip()
        texto = " ".join((it.pendencia, it.evidencia, it.recomendacao))
        if campo and it.pendencia.strip() and contradiz_esqueleto(
                campo, texto, it.contradiz_esqueleto, esqueleto, pipeline):
            logger.info("AUDITOR_FICHA_V3_ESQUELETO_BALDE1 campo=%s (veio do balde 2)", campo)
            b1.append(ItemBalde1V3(
                campo=campo, motivo=it.pendencia.strip(), regra=REGRA_ESQUELETO,
                correcao_sugerida=("Siga o esqueleto. " + it.recomendacao.strip())[
                    :MAX_CORRECAO_SUGERIDA],
                prova=it.prova, sem_prova_no_doc=it.sem_prova_no_doc,
                contradiz_esqueleto=True,
            ))
            continue
        b2.append(it)
    for it in saida.balde1:
        campo, motivo = it.campo.strip(), it.motivo.strip()
        if not campo or not motivo:
            continue
        regra = it.regra.strip()
        if contradiz_esqueleto(campo, f"{motivo} {it.correcao_sugerida}",
                               it.contradiz_esqueleto, esqueleto, pipeline):
            # Regra 6 (23/10/2026): o esqueleto e a prova. Fica no balde 1.
            b1.append(it.model_copy(update={
                "campo": campo, "motivo": motivo, "regra": _ancorar(regra),
                "correcao_sugerida": it.correcao_sugerida.strip(),
                "contradiz_esqueleto": True,
            }))
            continue
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
    # Regra 7 (23/10/2026): o codigo confere datas e numeros ANTES do LLM.
    d_fonte = achados_d_fonte(request, fontes_do_auditor(request, autos))
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
                                  achados=nav.achados,
                                  achados_codigo=[i.model_dump() for i in d_fonte])
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

    balde1, balde2 = normalizar_baldes_v3(saida, request.esqueleto, _pipeline(request))
    ja = {(i.campo, i.regra) for i in balde1}
    balde1 += [i for i in d_fonte if (i.campo, i.regra) not in ja]
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
    "REGRA_D_FONTE",
    "REGRA_ESQUELETO",
    "achados_d_fonte",
    "contradiz_esqueleto",
    "fontes_do_auditor",
    "auditar_ficha_v3",
    "normalizar_baldes_v3",
    "prompt_version",
    "validar_saida_v3",
]

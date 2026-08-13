"""INVESTIGADOR — tool-use em duas fases (onda 8, DESENHO §2/§6/§8.6).

O `montar_grafo` de hoje (one-shot com os textos inteiros no prompt) vira o
turno de FORMATACAO de um agente que investiga por ferramentas:

    FASE A (decisao)    — SEM response_schema/mime (a supressao de tool-calling
                          vem do schema, nao da ausencia de tools). O modelo
                          responde UMA chamada JSON por turno; o codigo executa.
    FASE B (formatacao) — COM response_mime_type JSON. Emite o GrafoAchatado.
                          Este turno nao decide nada.

Tres disciplinas de codigo (nunca de prompt):

- **Budget baixo** (40 calls/ficha): a factualidade cai ~42% de 2→150 calls
  com as metricas de superficie estaveis. Estouro ⇒ success=false motivo
  `budget` — o harness transforma em `indefinido` + fila humana.
- **Circuit breaker**: 3 falhas consecutivas de (ferramenta, doc) ⇒ ela some
  do menu daquele doc.
- **Ancora preenchida pelo CODIGO**: o modelo devolve `ancora_sid`; a Ancora
  completa (doc_hash, extractor_version, sha_texto, offset, bbox) sai de
  `DocumentoIndexado.ancora_de(sid)` — mata a classe "o modelo inventou o hash".

O Investigador NUNCA ve texto integral de documento: ve o INDICE (resumo
estrutural) e os envelopes dos Leitores. Envelope de Leitor sem `confianca` +
`objeto_da_confianca` e falha da ferramenta, nao resposta (§5.3).
"""

import importlib
import logging
from typing import Any, Callable, Optional

from ...providers import create_provider
from ...providers.base import LLMResponse
from ...utils.llm_json import parse_llm_json
from .ferramentas import Budget, CircuitBreaker, menu_do_investigador, parse_chamada
from .prompts import build_decisao_prompt, build_formatacao_prompt
from .schemas import GrafoAchatado, MontarGrafoRequest, MontarGrafoResponse

logger = logging.getLogger(__name__)

#: Turnos de decisao seguidos sem chamada parseavel antes de desistir da fase A.
_MAX_FALHAS_DE_PROTOCOLO = 3

#: Tentativas da fase B (emissao) — a re-emissao recebe os erros estruturais.
_MAX_TENTATIVAS_FORMATACAO = 2


def _leitor_default(nome: str) -> Optional[Callable]:
    """Resolve o Leitor (onda 4) por import tardio — as ondas 4 e 8 pousam em
    qualquer ordem; sem o modulo, a ferramenta falha tipada (e o breaker age)."""
    try:
        mod = importlib.import_module("src.agents.doc_reader.agent")
    except Exception:  # noqa: BLE001 — modulo ausente = ferramenta indisponivel
        try:
            mod = importlib.import_module("...doc_reader.agent", package=__name__)
        except Exception:  # noqa: BLE001
            return None
    return getattr(mod, nome, None)


async def investigar(
    request: MontarGrafoRequest,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    leitor_perguntar: Optional[Callable] = None,
    leitor_resumir: Optional[Callable] = None,
) -> MontarGrafoResponse:
    """Roda o loop de duas fases e devolve o MESMO contrato do montar_grafo.

    `leitor_*` sao injetaveis (testes/dublês); default = agente doc_reader.
    Nunca levanta: falha vira success=false + error tipado.
    """
    from .agent import (  # import tardio: evita ciclo agent -> investigador
        DEFAULT_MODEL,
        DEFAULT_PROVIDER,
        _validar_celulas,
        _validar_evidencias,
    )

    provider = provider or request.provider or DEFAULT_PROVIDER
    model = model or request.model or DEFAULT_MODEL
    llm = create_provider(provider)

    docs = _docs_indexados(request.documentos_indexados or {})
    indice = [
        {"doc_id": did, **_resumo_do_doc(d)} for did, d in sorted(docs.items())
    ]
    budget = Budget()
    breaker = CircuitBreaker()
    achados: list[dict] = []
    submissoes_aceitas: list[dict] = []
    paginas_por_doc: dict[str, int] = {}
    custo_total = 0.0
    modelo_usado = model
    falhas_protocolo = 0

    perguntar = leitor_perguntar or _leitor_default("perguntar")
    resumir = leitor_resumir or _leitor_default("resumir")

    # ── FASE A — decisao (schema-free) ──────────────────────────────────────
    while True:
        estouro = budget.estourado()
        if estouro:
            logger.warning("INVESTIGADOR_BUDGET job=%s: %s", request.celula_resultado, estouro)
            return MontarGrafoResponse(
                success=False, model=modelo_usado, cost_usd=round(custo_total, 6),
                error=f"budget: {estouro}",
            )

        prompt = build_decisao_prompt(
            dossie=request.dossie,
            indice=indice,
            achados=achados,
            perguntas_abertas=request.perguntas_abertas or [],
            celulas_congeladas=request.celulas_congeladas or [],
            menu=menu_do_investigador(sorted(docs), breaker),
            budget_restante=budget.max_tool_calls_por_ficha - budget.tool_calls,
            contrato_loop=request.contrato_loop or "",
        )
        # ⚑ Fase A NUNCA leva response_mime_type/response_schema (§6.1) — e o
        # teste `test_duas_fases` trava exatamente isso.
        resp: LLMResponse = await llm.agenerate(
            prompt=prompt, model=model, temperature=0.0, max_tokens=2048,
        )
        custo_total += _custo(resp)
        modelo_usado = resp.model or model

        chamada = parse_chamada(resp.text or "")
        if chamada is None:
            falhas_protocolo += 1
            achados.append({
                "tool": "_protocolo", "erro":
                "resposta sem chamada JSON valida — responda exatamente um JSON",
            })
            if falhas_protocolo >= _MAX_FALHAS_DE_PROTOCOLO:
                break  # segue pra formatacao com o que tem
            continue
        falhas_protocolo = 0
        if chamada.get("fim"):
            break

        budget.tool_calls += 1
        tool = chamada["tool"]
        args = chamada["args"]
        doc_id = str(args.get("doc_id") or "")

        if not breaker.disponivel(tool, doc_id):
            achados.append({
                "tool": tool, "doc_id": doc_id, "erro":
                "circuito ABERTO para esta ferramenta neste documento (3 falhas) — "
                "use outra ferramenta ou outro caminho",
            })
            continue

        resultado, ok = await _executar(
            tool, args, docs, paginas_por_doc, budget,
            perguntar, resumir, submissoes_aceitas,
            _validar_celulas, _validar_evidencias, request.celula_resultado,
        )
        custo_total += float(resultado.pop("_cost_usd", 0.0) or 0.0)
        achados.append({"tool": tool, "args": args, **resultado})
        if ok:
            breaker.registrar_sucesso(tool, doc_id)
        else:
            abriu = breaker.registrar_falha(tool, doc_id)
            if abriu:
                achados.append({
                    "tool": tool, "doc_id": doc_id,
                    "nota": "ferramenta removida do menu deste documento (circuit breaker)",
                })

    # ── FASE B — formatacao (schema-constrained) ────────────────────────────
    erros_estruturais = ""
    for tentativa in range(1, _MAX_TENTATIVAS_FORMATACAO + 1):
        prompt_b = build_formatacao_prompt(
            dossie=request.dossie,
            achados=achados,
            perguntas_abertas=request.perguntas_abertas or [],
            celulas_congeladas=request.celulas_congeladas or [],
            celula_resultado=request.celula_resultado,
            submissoes_aceitas=submissoes_aceitas,
        )
        if erros_estruturais:
            prompt_b += f"\n\n## ERROS da sua tentativa anterior (conserte TODOS)\n{erros_estruturais}"
        resp_b: LLMResponse = await llm.agenerate(
            prompt=prompt_b, model=model, temperature=0.0, max_tokens=16384,
            response_mime_type="application/json",
        )
        custo_total += _custo(resp_b)
        modelo_usado = resp_b.model or modelo_usado

        try:
            parsed = parse_llm_json(resp_b.text or "")
        except Exception as e:  # noqa: BLE001
            erros_estruturais = f"parse do JSON falhou: {e}"
            continue

        celulas, err = _validar_celulas(parsed)
        if err is None and not any(
            c["id"] == request.celula_resultado for c in celulas or []
        ):
            err = f"o grafo nao tem a celula de resultado {request.celula_resultado!r}"
        evidencias = None
        if err is None:
            evidencias, err = _validar_evidencias(parsed, celulas)
        if err is None:
            # `_validar_evidencias` normaliza pelo schema COMPAT (que ignora
            # ancora_sid) — devolvemos os campos de ancora do bruto antes de
            # ancorar por codigo.
            brutas = {
                str(e.get("celula_id")): e
                for e in (parsed.get("evidencias") or []) if isinstance(e, dict)
            }
            evidencias = [
                _ancorar({**e, **{
                    k: brutas.get(str(e.get("celula_id")), {}).get(k)
                    for k in ("ancora_sid", "ancora_pid", "politica")
                    if brutas.get(str(e.get("celula_id")), {}).get(k) is not None
                }}, docs)
                for e in evidencias or []
            ]
            grau = parsed.get("grau_sugerido")
            return MontarGrafoResponse(
                success=True,
                celulas=celulas or [],
                evidencias=evidencias,
                grau_sugerido=grau if grau in ("exato", "teto", "piso") else None,
                piso=_float_ou_none(parsed.get("piso")),
                teto=_float_ou_none(parsed.get("teto")),
                observacao=str(parsed.get("observacao") or ""),
                model=modelo_usado,
                cost_usd=round(custo_total, 6),
                error=None,
            )
        erros_estruturais = err or "erro estrutural"
        logger.info("INVESTIGADOR_FORMATACAO_REJEITADA t=%d: %s", tentativa, err)

    return MontarGrafoResponse(
        success=False, model=modelo_usado, cost_usd=round(custo_total, 6),
        error=f"formatacao rejeitada apos {_MAX_TENTATIVAS_FORMATACAO} tentativas: {erros_estruturais}",
    )


# ── execucao das ferramentas ────────────────────────────────────────────────

async def _executar(
    tool: str,
    args: dict,
    docs: dict[str, Any],
    paginas_por_doc: dict[str, int],
    budget: Budget,
    perguntar: Optional[Callable],
    resumir: Optional[Callable],
    submissoes_aceitas: list[dict],
    _validar_celulas: Callable,
    _validar_evidencias: Callable,
    celula_resultado: str,
) -> tuple[dict, bool]:
    """Executa UMA ferramenta. Devolve (resultado_para_achados, sucesso)."""
    doc_id = str(args.get("doc_id") or "")

    if tool in ("perguntar_ao_documento", "resumir_com_missao"):
        fn = perguntar if tool == "perguntar_ao_documento" else resumir
        if fn is None:
            return {"erro": "Leitor indisponivel neste deploy (onda 4 ausente)"}, False
        if doc_id not in docs:
            return {"erro": f"doc_id desconhecido: {doc_id!r}"}, False
        try:
            envelope = await fn(doc_id=doc_id, documento=docs[doc_id], **{
                k: v for k, v in args.items() if k not in ("doc_id",)
            })
        except Exception as e:  # noqa: BLE001 — falha do Leitor e falha da tool
            return {"erro": f"Leitor falhou: {e}"}, False
        envelope = dict(envelope or {})
        # §5.3 — confianca EM CAMPO e obrigatoria; sem ela nao e resposta.
        c = envelope.get("confianca")
        if (isinstance(c, bool) or not isinstance(c, (int, float))
                or not str(envelope.get("objeto_da_confianca") or "").strip()):
            return {"erro": (
                "envelope do Leitor sem confianca/objeto_da_confianca em campo — "
                "resposta rejeitada"
            ), "_cost_usd": envelope.get("cost_usd", 0.0)}, False
        return {"resultado": envelope, "_cost_usd": envelope.get("cost_usd", 0.0)}, True

    if tool == "pedir_pagina":
        if doc_id not in docs:
            return {"erro": f"doc_id desconhecido: {doc_id!r}"}, False
        usadas = paginas_por_doc.get(doc_id, 0)
        if usadas >= budget.max_paginas_por_doc:
            return {"erro": (
                f"teto de {budget.max_paginas_por_doc} paginas cruas por documento "
                "atingido — pergunte ao Leitor em vez de ler pagina"
            )}, False
        try:
            pagina = int(args.get("pagina"))
        except (TypeError, ValueError):
            return {"erro": "args.pagina deve ser inteiro"}, False
        doc = docs[doc_id]
        sentencas = [
            {"sid": s.sid, "texto": s.texto}
            for s in doc.sentencas_da_pagina(pagina)
        ]
        if not sentencas:
            return {"erro": f"pagina {pagina} sem sentencas neste documento"}, False
        paginas_por_doc[doc_id] = usadas + 1
        return {"resultado": {"pagina": pagina, "sentencas": sentencas}}, True

    if tool == "submeter_celulas":
        parsed = {"celulas": args.get("celulas") or [],
                  "evidencias": args.get("evidencias") or []}
        celulas, err = _validar_celulas(parsed)
        if err is None:
            _evs, err = _validar_evidencias(parsed, celulas)
        if err is not None:
            return {"rejeitadas": [{"codigo": "estrutura", "mensagem": err}]}, False
        aceitas = [c["id"] for c in celulas or []]
        submissoes_aceitas.append(parsed)
        return {"resultado": {"aceitas": aceitas, "rejeitadas": []}}, True

    return {"erro": f"ferramenta desconhecida: {tool!r}"}, False


# ── helpers ─────────────────────────────────────────────────────────────────

def _docs_indexados(raw: dict[str, Any]) -> dict[str, Any]:
    """doc_id -> DocumentoIndexado (shared onda 1). Entrada invalida e pulada
    com log — um doc quebrado nao derruba a investigacao dos outros."""
    from garantis_shared.calculo_fichas.documento import DocumentoIndexado

    out: dict[str, Any] = {}
    for did, d in (raw or {}).items():
        try:
            out[str(did)] = d if isinstance(d, DocumentoIndexado) else DocumentoIndexado.from_dict(d)
        except Exception as e:  # noqa: BLE001
            logger.warning("INVESTIGADOR_DOC_INVALIDO doc=%s: %r", did, e)
    return out


def _resumo_do_doc(doc: Any) -> dict:
    try:
        return dict(doc.resumo())
    except Exception:  # noqa: BLE001
        return {"paginas": list(getattr(doc, "paginas", lambda: [])())}


def _ancorar(evidencia: dict, docs: dict[str, Any]) -> dict:
    """Preenche a `ancora` COMPLETA a partir do `ancora_sid` — por codigo.

    sid inexistente ⇒ ancora=None e o fallback fuzzy do shared decide (a
    onda 5 ja rejeita ancora podre com motivo tipado; nao inventamos nada aqui).
    """
    ev = dict(evidencia)
    sid = ev.get("ancora_sid")
    doc = docs.get(str(ev.get("documento") or ""))
    if sid and doc is not None:
        try:
            ancora = doc.ancora_de(str(sid))
        except Exception:  # noqa: BLE001
            ancora = None
        if ancora is not None:
            ev["ancora"] = ancora.to_dict()
    return ev


def _custo(resp: LLMResponse) -> float:
    return float((resp.metadata or {}).get("cost_usd", 0.0) or 0.0)


def _float_ou_none(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


__all__ = ["investigar"]

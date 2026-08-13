"""Agente CALCULADOR (C4) — monta o grafo de celulas com evidencia por dado.

Stateless. Usa o factory (provider default = Gemini) em JSON mode. O agente NAO
produz o numero: produz o grafo que o motor deterministico do garantis_shared
resolve. Por isso a validacao aqui e de ESTRUTURA, nunca de aritmetica.

Validacao em duas camadas, de proposito:

- **Aqui (barata, na fronteira):** shape do JSON, ramos disjuntos dado/formula,
  id de taxa proibido, evidencia para todo dado 'extraida'. Erro barato volta
  como `success=false` sem atravessar a rede de novo.
- **No shared (definitiva):** gramatica da expressao, ciclo, origem assumida em
  juros, trecho conferido contra o documento, recomputo, sanity. E la que mora
  o gate — este agente e conveniencia, nao autoridade.

Como o write-fields: qualquer falha devolve `success=false` + error claro
(nunca levanta), propagando `model`/`cost_usd` mesmo no erro — o harness
transforma isso em rejeicao de rodada e itera com contexto.
"""

import logging
import math
import os
from typing import Any, Optional

from ...providers import create_provider
from ...providers.base import LLMResponse
from ...utils.llm_json import parse_llm_json
from .prompts import build_montar_grafo_prompt
from .schemas import CelulaDado, CelulaFormula, Evidencia, MontarGrafoRequest, MontarGrafoResponse

logger = logging.getLogger(__name__)

DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER", "gemini")

#: Modelo do CALCULADOR. Um calculo que vira garantia bilionaria nao roda em
#: flash-lite — foi exatamente o default do V3 (`optimize_cost`) e a economia
#: apareceu como erro de 3x. O auditor usa modelo DIFERENTE (ver
#: auditor_evidencias.agent): dois erros correlacionados do mesmo modelo se
#: confirmariam mutuamente.
#:
#: ⚠️ FIX 2026-08-13 (era `gemini-3.1-pro-preview`): aquele id da 404 no Vertex
#: — e a casa roda GEMINI_BACKEND=vertex em TODOS os cloudbuilds, entao o
#: calculador simplesmente nao respondia em prod. Pior que o 404: o id nao
#: existe em `garantis_shared.llm_models.MODELS`, entao `get_model_pricing()`
#: devolve 0/0 e o custo sai SILENCIOSAMENTE ZERADO do ledger — o mesmo
#: mecanismo que ja escondeu US$ 97,61 em 39.309 calls e reincidiu duas vezes.
#: `gemini-3.5-flash` esta no catalogo (1.50/9.00, preco confirmado na fatura),
#: e nao-preview e segue DIFERENTE do auditor, que hoje roda `gemini-2.5-flash`
#: (anti-conluio preservado). ⚠️ Mas 2.5-flash APOSENTA em 2026-10-16
#: (RETIRE_2_5_FAMILY): antes disso o auditor precisa de um id novo, e trocar os
#: dois pro mesmo modelo mata a premissa do desenho — ver PR #345.
#: Isto e FIX DE BUG, nao escolha de papel: a proposta formal de ROLES para
#: fichas (`ficha_investigador` etc.) vive no PR #345 do garantis-shared e
#: continua sendo decisao do dono — quando ela entrar, este default vira
#: `model_for("ficha_investigador")`.
DEFAULT_MODEL = os.getenv(
    "CALCULO_FICHA_MODEL", os.getenv("DEFAULT_MODEL", "gemini-3.5-flash")
)

#: Grafo grande e sinal de caso mal decomposto, e o custo de validar explode.
MAX_CELULAS = 120


def _validar_celulas(parsed: dict) -> tuple[Optional[list[dict]], Optional[str]]:
    """Valida a lista de celulas: shape, ramos disjuntos, ids unicos.

    Devolve `(celulas, None)` ou `(None, erro)` na primeira falha. Nao valida a
    gramatica da expressao nem o grafo — isso e do shared, que tem o parser.
    """
    celulas = parsed.get("celulas")
    if not isinstance(celulas, list) or not celulas:
        return None, "resposta sem lista `celulas` nao-vazia"
    if len(celulas) > MAX_CELULAS:
        return None, f"grafo com {len(celulas)} celulas excede o maximo de {MAX_CELULAS}"

    vistos: set[str] = set()
    out: list[dict] = []
    for i, c in enumerate(celulas):
        if not isinstance(c, dict):
            return None, f"celula[{i}] deveria ser objeto, veio {type(c).__name__}"
        tipo = c.get("tipo")
        try:
            if tipo == "dado":
                # Ramo disjunto: `dado` com expressao seria o LLM calculando
                # escondido dentro de uma folha.
                if "expressao" in c and c.get("expressao"):
                    return None, (
                        f"celula[{i}] id={c.get('id')!r} e 'dado' mas traz `expressao` — "
                        "dado carrega valor, formula carrega expressao"
                    )
                modelo: Any = CelulaDado(**c)
            elif tipo == "formula":
                if c.get("valor") is not None:
                    return None, (
                        f"celula[{i}] id={c.get('id')!r} e 'formula' mas traz `valor` — "
                        "o valor de uma formula e calculado, nunca informado"
                    )
                modelo = CelulaFormula(**c)
            else:
                return None, f"celula[{i}] tipo deve ser 'dado' ou 'formula', veio {tipo!r}"
        except Exception as e:  # noqa: BLE001 — ValidationError do pydantic
            return None, f"celula[{i}] invalida: {e}"

        if modelo.id in vistos:
            return None, f"id de celula duplicado: {modelo.id!r}"
        vistos.add(modelo.id)
        out.append(modelo.model_dump())
    return out, None


def _validar_evidencias(
    parsed: dict, celulas: list[dict]
) -> tuple[Optional[list[dict]], Optional[str]]:
    """Valida evidencias e cobra uma para cada dado 'extraida'.

    'factual' dispensa evidencia (decorre de norma, nao de documento) mas o
    prompt exige `nota` com o dispositivo — quem cobra a nota e o auditor.
    """
    brutas = parsed.get("evidencias") or []
    if not isinstance(brutas, list):
        return None, f"`evidencias` deveria ser lista, veio {type(brutas).__name__}"

    out: list[dict] = []
    for i, e in enumerate(brutas):
        if not isinstance(e, dict):
            return None, f"evidencia[{i}] deveria ser objeto, veio {type(e).__name__}"
        try:
            out.append(Evidencia(**e).model_dump())
        except Exception as exc:  # noqa: BLE001
            return None, f"evidencia[{i}] invalida: {exc}"

    ids_com_ev = {e["celula_id"] for e in out}
    faltando = sorted(
        c["id"] for c in celulas
        if c.get("tipo") == "dado" and c.get("origem") == "extraida"
        and c["id"] not in ids_com_ev
    )
    if faltando:
        return None, (
            f"dados 'extraida' sem evidencia citada: {faltando} — todo valor lido "
            "do documento carrega documento, pagina, trecho literal e localizador"
        )

    ids_celulas = {c["id"] for c in celulas}
    orfas = sorted(e["celula_id"] for e in out if e["celula_id"] not in ids_celulas)
    if orfas:
        return None, f"evidencias para celulas inexistentes: {orfas}"
    return out, None


async def montar_grafo(
    request: MontarGrafoRequest | dict,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> MontarGrafoResponse:
    """Monta o grafo de celulas a partir do dossie + documentos + premissas V3.

    Nunca levanta: falha vira `success=false` + `error`, que o harness registra
    como rejeicao da rodada e reenvia com contexto.
    """
    if isinstance(request, dict):
        request = MontarGrafoRequest(**request)

    provider = provider or request.provider or DEFAULT_PROVIDER
    model = model or request.model or DEFAULT_MODEL

    llm_provider = create_provider(provider)
    prompt = build_montar_grafo_prompt(request)

    response: LLMResponse = await llm_provider.agenerate(
        prompt=prompt,
        model=model,
        temperature=0.0,
        response_mime_type="application/json",
        max_tokens=16384,
    )
    raw = response.text or ""
    used_model = response.model or model
    cost_usd = (response.metadata.get("cost_usd", 0.0) if response.metadata else 0.0)

    def _falha(erro: str) -> MontarGrafoResponse:
        logger.info("CALCULO_FICHA_FAIL: %s", erro)
        return MontarGrafoResponse(
            success=False, model=used_model, cost_usd=cost_usd, error=erro
        )

    try:
        parsed = parse_llm_json(raw)
    except Exception as e:  # noqa: BLE001
        logger.warning("CALCULO_FICHA_PARSE_FAIL: %r | head=%r", e, raw[:200])
        return _falha(f"parse do JSON do LLM falhou: {e}")

    celulas, err = _validar_celulas(parsed)
    if err is not None:
        return _falha(err)
    assert celulas is not None

    if not any(c["id"] == request.celula_resultado for c in celulas):
        return _falha(
            f"o grafo nao tem a celula de resultado {request.celula_resultado!r} — "
            "a garantia final precisa de um id explicito"
        )

    evidencias, err = _validar_evidencias(parsed, celulas)
    if err is not None:
        return _falha(err)
    assert evidencias is not None

    grau = parsed.get("grau_sugerido")
    if grau not in ("exato", "teto", "piso", None):
        grau = None

    return MontarGrafoResponse(
        success=True,
        celulas=celulas,
        evidencias=evidencias,
        grau_sugerido=grau,
        piso=_float_ou_none(parsed.get("piso")),
        teto=_float_ou_none(parsed.get("teto")),
        observacao=str(parsed.get("observacao") or ""),
        model=used_model,
        cost_usd=cost_usd,
        error=None,
    )


def _float_ou_none(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


__all__ = ["montar_grafo"]

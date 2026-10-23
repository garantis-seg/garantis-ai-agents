"""Agente AUDITOR DE FICHA (S6), versao 2: dois baldes.

Stateless. Confere a ficha (S4, ja aprovada na S5) contra o dossie, o
esqueleto da S3b e, quando existe, o gabarito. Devolve o veredito do Livro
(§10.2) e os campos v1 que o shared atual le (ver schemas.py).

Modelo DIFERENTE do redator, por desenho: o mesmo modelo que escreveu
confirmaria os proprios erros. O papel `ficha_auditoria_texto` do registro
do shared garante isso.

FAIL-SAFE. Falha do agente devolve `success=false`, `veredito=None`,
`aprovado=false` e `auditor_enabled=false`. O agente nao inventa reprovacao
nem aprovacao. O par `aprovado=false + auditor_enabled=false` e o estado "nao
auditada". O runner do shared decide bloquear ou seguir.

Nao ha ferramenta aqui, de proposito: o verificador com ferramenta deu muito
mais falso-positivo. O dossie inteiro vai no contexto.
"""

import logging
from typing import Any, Optional

from garantis_shared.llm_models import model_for
from pydantic import ValidationError

from ...providers import create_provider
from ...providers.base import LLMResponse
from ...utils.llm_json import parse_llm_json
from .checklist import REGRAS_CONHECIDAS, SO_BALDE_2
from .prompts import PROMPT_VERSION, build_auditar_ficha_prompt, build_prompt_de_correcao
from .schemas import (
    AuditarFichaRequest,
    AuditarFichaResponse,
    ItemBalde1,
    ItemBalde2,
    SaidaAuditor,
)

logger = logging.getLogger(__name__)

DEFAULT_PROVIDER = "gemini"

DEFAULT_MODEL = model_for("ficha_auditoria_texto")

#: Rodadas do modelo por chamada: a 1a e 1 correcao. Decisao de 22/10/2026
#: (pedido da S6): "alerta sem resposta -> 422 estruturado para retry (1
#: rodada)". O teto de rodadas e classe B: so o Alfredo muda.
MAX_RODADAS = 2

_MARCA_ANCORA = "(ancora nao reconhecida)"


# ── Regras do codigo ───────────────────────────────────────────────────────


def calcular_veredito(balde1: list[ItemBalde1], balde2: list[ItemBalde2]) -> str:
    """O veredito sai dos baldes. O modelo nao decide (22/10/2026).

    - `retida`: so com item do balde 2 de grau `alta`.
    - `aprovada_com_correcoes`: ha balde 1 e nenhum balde 2 de grau alta.
    - `aprovada`: nenhum balde 1 e nenhum balde 2 de grau alta. Balde 2 de
      grau media ou baixa nao muda o veredito: vira pendencia no `meta`.
    """
    if any(p.grau == "alta" for p in balde2):
        return "retida"
    if balde1:
        return "aprovada_com_correcoes"
    return "aprovada"


def _ancorar(regra: str) -> str:
    """Regra fora de `REGRAS_CONHECIDAS`: o item FICA, com a marca.

    O defeito pode ser real. Sumir com o item seria aprovar em silencio.
    """
    regra = regra.strip()
    if regra in REGRAS_CONHECIDAS:
        return regra
    return f"{regra or 'sem-ancora'} {_MARCA_ANCORA}"


def _normalizar_baldes(saida: SaidaAuditor) -> tuple[list[ItemBalde1], list[ItemBalde2]]:
    """Aplica as regras do codigo sobre os baldes que o modelo devolveu.

    1. Item do balde 1 sem campo ou sem motivo sai: ele nao e acionavel.
    2. Regra fora da lista leva a marca "(ancora nao reconhecida)".
    3. Item do balde 1 com regra "SO balde 2" (kill-check, esgotamento) vai ao
       balde 2 com grau `media`. O redator nao conserta "o caso nao deveria
       existir". Decisao de 22/10/2026 (DECIDI-SOZINHO): grau media, e nao
       alta, porque o modelo nao deu o grau. Um humano le e decide.
    """
    b1: list[ItemBalde1] = []
    b2: list[ItemBalde2] = list(saida.balde2)
    for it in saida.balde1:
        campo, motivo = it.campo.strip(), it.motivo.strip()
        if not campo or not motivo:
            continue
        regra = it.regra.strip()
        if regra in SO_BALDE_2:
            b2.append(ItemBalde2(
                campo=campo,
                pendencia=motivo,
                grau="media",
                evidencia=it.correcao_sugerida or "(o modelo pos o item no balde 1)",
                recomendacao=f"Conferir o item {regra} do checklist. O codigo moveu "
                             "o item do balde 1 para o balde 2.",
            ))
            continue
        b1.append(ItemBalde1(
            campo=campo, motivo=motivo, regra=_ancorar(regra),
            correcao_sugerida=it.correcao_sugerida.strip(),
        ))
    return b1, b2


def validar_saida(
    parsed: Any, request: AuditarFichaRequest
) -> tuple[Optional[SaidaAuditor], list[dict[str, Any]]]:
    """Valida o JSON do modelo. Devolve (saida, erros).

    Cada erro tem o formato `{campo, erro, valor_anterior}` (plano, Parte 1.2,
    item 4). Lista vazia = saida valida. Um erro aqui e um 422: o agente
    devolve a lista ao modelo e pede outra rodada.
    """
    if not isinstance(parsed, dict):
        return None, [{
            "campo": "_raiz", "erro": "a resposta tem de ser um objeto JSON",
            "valor_anterior": type(parsed).__name__,
        }]
    try:
        saida = SaidaAuditor.model_validate(parsed)
    except ValidationError as e:
        erros = []
        for err in e.errors():
            loc = ".".join(str(x) for x in err.get("loc", ())) or "_raiz"
            erros.append({
                "campo": loc, "erro": err.get("msg", "invalido"),
                "valor_anterior": err.get("input"),
            })
        return None, erros

    erros: list[dict[str, Any]] = []

    codigos = [a.codigo for a in request.alertas]
    respondidos = [r.codigo for r in saida.alertas_respondidos]
    for cod in codigos:
        if cod not in respondidos:
            erros.append({
                "campo": "alertas_respondidos",
                "erro": f"alerta {cod} sem resposta (confirmado | refutado)",
                "valor_anterior": None,
            })
    for cod in respondidos:
        if cod not in codigos:
            erros.append({
                "campo": "alertas_respondidos",
                "erro": f"codigo {cod} nao existe na lista de alertas",
                "valor_anterior": cod,
            })

    if saida.divergencias_gabarito and not request.gabarito:
        erros.append({
            "campo": "divergencias_gabarito",
            "erro": "nao ha gabarito nesta auditoria: a lista tem de ser vazia",
            "valor_anterior": len(saida.divergencias_gabarito),
        })
    elif saida.divergencias_gabarito:
        campos_acusados = {i.campo.strip() for i in saida.balde1} | {
            i.campo.strip() for i in saida.balde2
        }
        for d in saida.divergencias_gabarito:
            if d.e_erro and d.campo.strip() not in campos_acusados:
                erros.append({
                    "campo": "divergencias_gabarito",
                    "erro": (
                        f"divergencia de FATO em {d.campo} (e_erro=true) sem item "
                        "no balde 1 ou no balde 2 do mesmo campo"
                    ),
                    "valor_anterior": d.model_dump(),
                })

    return (saida if not erros else None), erros


# ── Montagem da resposta ───────────────────────────────────────────────────


def _pendencias(veredito: str, balde2: list[ItemBalde2]) -> list[str]:
    """O balde 2 em texto, para o `pendencias` que o shared ja carrega ao `meta`.

    O shared atual so le `aprovado`, `reprovacoes` e `pendencias`. Com isso, o
    balde 2 ja chega ao `meta` antes da migracao da S6 do worker.
    """
    out = []
    if veredito == "retida":
        out.append("[S6] Ficha RETIDA: o balde 2 tem pendencia de grau alta.")
    for p in balde2:
        out.append(
            f"[S6 balde 2 · {p.grau}] {p.campo}: {p.pendencia} "
            f"(evidencia: {p.evidencia}; recomendacao: {p.recomendacao})"
        )
    return out


def _falha(
    erro: str,
    modelo: str,
    cost_usd: float = 0.0,
    rodadas: int = 0,
    erros_validacao: Optional[list[dict[str, Any]]] = None,
) -> AuditarFichaResponse:
    """Falha de CHAMADA: nao auditada. Nem aprovada, nem reprovada."""
    return AuditarFichaResponse(
        success=False,
        veredito=None,
        aprovado=False,
        auditor_enabled=False,
        modelo=modelo,
        reprovacoes=[],
        pendencias=[
            "auditor de ficha (S6) nao concluiu: " + erro + ". A ficha NAO foi "
            "auditada. Ela passou apenas pelo validador deterministico (S5)."
        ],
        erros_validacao=erros_validacao or [],
        rodadas=rodadas,
        prompt_version=PROMPT_VERSION,
        model=modelo,
        cost_usd=cost_usd,
        error=erro,
    )


def _custo(resp: LLMResponse) -> float:
    return float((resp.metadata or {}).get("cost_usd", 0.0) or 0.0)


async def auditar_ficha(
    request: AuditarFichaRequest | dict,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> AuditarFichaResponse:
    """Audita a ficha. Nunca levanta: toda falha vira `success=false`."""
    if isinstance(request, dict):
        request = AuditarFichaRequest(**request)

    provider = provider or request.provider or DEFAULT_PROVIDER
    model = model or request.model or DEFAULT_MODEL

    if not request.ficha:
        return _falha("nenhuma ficha para auditar", model)
    if not request.dossie.strip():
        # Sem dossie nao ha contra o que conferir. Aprovar aqui seria um
        # "aprovado" que nao olhou nada.
        return _falha(
            "dossie vazio: sem fonte de verdade nao ha auditoria de fidelidade",
            model,
        )

    llm_provider = create_provider(provider)
    prompt_base = build_auditar_ficha_prompt(request)
    prompt = prompt_base
    cost_usd = 0.0
    used_model = model
    erros: list[dict[str, Any]] = []
    saida: Optional[SaidaAuditor] = None

    for rodada in range(1, MAX_RODADAS + 1):
        response: LLMResponse = await llm_provider.agenerate(
            prompt=prompt,
            model=model,
            temperature=0.0,  # conferencia e determinista
            response_mime_type="application/json",
            max_tokens=16384,
        )
        raw = response.text or ""
        used_model = response.model or model
        cost_usd += _custo(response)

        try:
            parsed = parse_llm_json(raw)
        except Exception as e:  # noqa: BLE001
            logger.warning("AUDITOR_FICHA_PARSE_FAIL rodada=%d: %r | head=%r", rodada, e, raw[:200])
            erros = [{"campo": "_raiz", "erro": f"JSON invalido: {e}", "valor_anterior": raw[:500]}]
        else:
            saida, erros = validar_saida(parsed, request)

        if saida is not None:
            break
        logger.info("AUDITOR_FICHA_422 rodada=%d erros=%s", rodada, erros)
        if rodada < MAX_RODADAS:
            prompt = build_prompt_de_correcao(prompt_base, raw, erros)
    else:
        return _falha(
            f"422: saida do modelo invalida depois de {MAX_RODADAS} rodadas",
            used_model, cost_usd, rodadas=MAX_RODADAS, erros_validacao=erros,
        )

    balde1, balde2 = _normalizar_baldes(saida)
    veredito = calcular_veredito(balde1, balde2)
    if saida.veredito and saida.veredito != veredito:
        # O codigo vence. O log mostra a divergencia para a calibragem.
        logger.info(
            "AUDITOR_FICHA_VEREDITO_DIVERGENTE modelo=%s codigo=%s",
            saida.veredito, veredito,
        )

    reprovacoes = [
        {"campo": i.campo, "motivo": i.motivo, "regra": i.regra} for i in balde1
    ]
    logger.info(
        "AUDITOR_FICHA_OK veredito=%s balde1=%d balde2=%d rodada=%d model=%s",
        veredito, len(balde1), len(balde2), rodada, used_model,
    )
    return AuditarFichaResponse(
        success=True,
        veredito=veredito,
        balde1=balde1,
        balde2=balde2,
        nao_confirmado=[s for s in saida.nao_confirmado if s.strip()],
        alertas_respondidos=saida.alertas_respondidos,
        divergencias_gabarito=saida.divergencias_gabarito,
        # Campos v1 derivados (o shared migra na S6 do worker).
        aprovado=veredito != "retida",
        auditor_enabled=True,
        modelo=used_model,
        reprovacoes=reprovacoes,
        pendencias=_pendencias(veredito, balde2),
        rodadas=rodada,
        prompt_version=PROMPT_VERSION,
        model=used_model,
        cost_usd=cost_usd,
        error=None,
    )


__all__ = [
    "auditar_ficha",
    "calcular_veredito",
    "validar_saida",
    "DEFAULT_MODEL",
    "MAX_RODADAS",
    "REGRAS_CONHECIDAS",
]

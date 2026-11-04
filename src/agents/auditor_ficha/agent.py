"""Agente AUDITOR DE FICHA (S6): a porta da rota e as regras do codigo.

Stateless. A auditoria mora em `agent_v3.py`: o auditor abre os autos (o
`nucleo` e o `indice_navegavel` do request) e cada item dos baldes leva prova
de documento. Este modulo guarda o que vale para ela inteira: o veredito
calculado pelo codigo, a ancora da regra, a conferencia dos alertas, o texto
das pendencias e a resposta de falha.

Modelo DIFERENTE do redator, por desenho: o mesmo modelo que escreveu
confirmaria os proprios erros. O papel `ficha_auditoria_texto` do registro
do shared garante isso.

FAIL-SAFE. Falha do agente devolve `success=false`, `veredito=None`,
`aprovado=false` e `auditor_enabled=false`. O agente nao inventa reprovacao
nem aprovacao. O par `aprovado=false + auditor_enabled=false` e o estado "nao
auditada". O runner do shared decide bloquear ou seguir.
"""

from typing import Any, Optional

from garantis_shared.llm_models import model_for

from .checklist import REGRAS_CONHECIDAS
from .schemas import (
    AuditarFichaRequest,
    AuditarFichaResponse,
    ItemBalde1,
    ItemBalde2,
    SaidaAuditor,
)

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


def erros_de_alertas(saida: SaidaAuditor, request: AuditarFichaRequest) -> list[dict[str, Any]]:
    """Todo alerta de entrada tem resposta, e nenhuma resposta e de alerta estranho."""
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
    return erros


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
        model=modelo,
        cost_usd=cost_usd,
        error=erro,
    )


async def auditar_ficha(
    request: AuditarFichaRequest | dict,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> AuditarFichaResponse:
    """Audita a ficha lendo os autos. Nunca levanta: toda falha vira `success=false`.

    O schema ja recusou o corpo sem `nucleo` e `indice_navegavel` (422).
    """
    if isinstance(request, dict):
        request = AuditarFichaRequest(**request)

    provider = provider or request.provider or DEFAULT_PROVIDER
    model = model or request.model or DEFAULT_MODEL

    # Import tardio: o agent_v3 importa as regras deste modulo.
    from .agent_v3 import auditar_ficha_v3

    return await auditar_ficha_v3(request, provider, model)


__all__ = [
    "auditar_ficha",
    "erros_de_alertas",
    "calcular_veredito",
    "DEFAULT_MODEL",
    "MAX_RODADAS",
    "REGRAS_CONHECIDAS",
]

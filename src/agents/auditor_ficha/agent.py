"""Agente AUDITOR DE FICHA (S6) — o ultimo portao antes de a ficha ser persistida.

Stateless. Confere a ficha redigida (S4, ja aprovada no S5 deterministico)
contra o dossie e contra o checklist do Livro, e devolve o veredicto no
contrato EXATO de `garantis_shared.fichas.runner.auditar`.

Modelo DIFERENTE do redator, por desenho: auditar com o mesmo modelo que
escreveu e pedir a alguem que revise o proprio trabalho — os erros sao
correlacionados e se confirmam mutuamente (mesma razao do auditor_evidencias
do C4, e o que o achado A-1 do QA-B1 mediu em prod).

DIRECAO DO FAIL-SAFE — aqui ela e o OPOSTO da do auditor_evidencias, de
proposito. La, falha do agente derruba a RODADA (o harness tenta de novo). Aqui,
falha do agente devolve `success=false` com `aprovado=false` E
`auditor_enabled=false`: nao inventamos reprovacao (nao ha o que corrigir — o
S4 receberia um retry sem campo) e nao inventamos aprovacao (ninguem pode ler
"aprovado" como "auditado"). O par `aprovado=false + auditor_enabled=false` e
literalmente o estado "nao auditada", que o workflow ja sabe representar — e
quem decide bloquear ou seguir e o runner do shared, nao este repo.

Nao ha ferramenta aqui, de proposito: o verificador com ferramenta rendeu 5x
mais falso-positivo (PESQUISA-AGENTE-INVESTIGADOR-2026-08 §4). O dossie inteiro
vai no contexto e o modelo julga o que le.
"""

import logging
import os
from typing import Any, Optional

from ...providers import create_provider
from ...providers.base import LLMResponse
from ...utils.llm_json import parse_llm_json
from .prompts import build_auditar_ficha_prompt
from .schemas import AuditarFichaRequest, AuditarFichaResponse, Reprovacao

logger = logging.getLogger(__name__)

DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER", "gemini")

#: Papel deste agente no registro de modelos do shared.
_ROLE = "ficha_auditoria_texto"

#: Default LITERAL, usado enquanto o papel nao existir no wheel instalado.
#: TODO(garantis-shared#345): quando o PR #345 (roles de fichas em
#: `garantis_shared.llm_models.ROLES`) estiver mergeado e o pin do
#: requirements.txt subir, este literal vira apenas o ultimo fallback — a
#: resolucao abaixo ja prefere o ROLES automaticamente, sem mudanca de codigo.
#: Medido em 13/08/2026 no pin vigente (garantis-shared==1.459.0): o papel
#: `ficha_auditoria_texto` NAO existe (ROLES tem 7 papeis, todos de engine/
#: leitor/vision), entao hoje quem responde e este literal.
_DEFAULT_MODEL_LITERAL = "gemini-3.1-flash-lite"


def _modelo_do_papel() -> Optional[str]:
    """Modelo do papel `ficha_auditoria_texto` no ROLES do shared, se existir.

    Tolerante de proposito: o wheel pinado pode nao ter o registro (PR #345 nao
    mergeado), e a forma do valor pode ser string ou dict — ler o registro nao
    pode derrubar o agente. Qualquer surpresa devolve None e cai no literal.
    """
    try:
        from garantis_shared.llm_models import ROLES  # import local: opcional
    except Exception:  # noqa: BLE001 — wheel antigo/sem o modulo
        return None
    try:
        entrada = ROLES.get(_ROLE)
    except Exception:  # noqa: BLE001
        return None
    if isinstance(entrada, str) and entrada.strip():
        return entrada.strip()
    if isinstance(entrada, dict):
        for chave in ("model", "modelo", "default", "id"):
            val = entrada.get(chave)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return None


def resolver_modelo() -> str:
    """Precedencia: env explicita -> papel do ROLES -> literal.

    `FICHA_AUDITORIA_TEXTO_MODEL` vem PRIMEIRO e NAO cai em `DEFAULT_MODEL`
    (diferente dos agentes antigos) — foi exatamente o `X or DEFAULT_MODEL` que
    colapsou calculador e auditor no mesmo modelo em prod (achado A-1). Herdar
    o DEFAULT_MODEL aqui reintroduziria o mesmo silencio: o redator tambem o
    herda, e os dois voltariam a ser o mesmo modelo sem ninguem perceber.
    """
    env = os.getenv("FICHA_AUDITORIA_TEXTO_MODEL")
    if env and env.strip():
        return env.strip()
    return _modelo_do_papel() or _DEFAULT_MODEL_LITERAL


#: IDs de regra aceitos no campo `regra`. Um ID fora desta lista denuncia
#: reprovacao inventada — o modelo alucinou uma autoridade que o Livro nao tem.
#: Nao DESCARTAMOS a reprovacao por isso (o defeito apontado pode ser real e
#: descartar em silencio seria aprovar em silencio): marcamos a ancora como
#: nao reconhecida e deixamos visivel para quem le o veredicto.
REGRAS_CONHECIDAS: frozenset[str] = frozenset({
    "S2", "S7", "S10", "S12", "S13", "S14", "S15", "S16", "S17", "S19",
    "S40", "S40-cross", "S44", "E14", "E19", "E14/S13", "E19/S14",
    "A31", "A31/S17", "S44/CON-05", "CON-05", "CON-11", "VAL-15", "TER-04",
    "B07", "B05-09", "B05-10", "B05-43", "B05-09/B05-10", "B05-43/CON-11",
})


def _normalizar_reprovacoes(parsed: Any) -> tuple[list[dict], Optional[str]]:
    """Extrai a lista tipada de reprovacoes do JSON do modelo.

    Descarta item malformado (sem campo ou sem motivo) — ele nao aciona retry
    nenhum no S4, entao manter seria poluir o veredicto. Reprovacao com `regra`
    fora de `REGRAS_CONHECIDAS` e MANTIDA, com a ancora anotada como nao
    reconhecida: o defeito pode ser real, e o inverso (sumir com ela) seria
    aprovar em silencio.
    """
    if not isinstance(parsed, dict):
        return [], f"resposta nao e objeto JSON (veio {type(parsed).__name__})"
    brutas = parsed.get("reprovacoes")
    if brutas is None:
        return [], "resposta sem a chave `reprovacoes`"
    if not isinstance(brutas, list):
        return [], f"`reprovacoes` deveria ser lista (veio {type(brutas).__name__})"

    out: list[dict] = []
    for item in brutas:
        if not isinstance(item, dict):
            continue
        try:
            rep = Reprovacao(**item)
        except Exception:  # noqa: BLE001 — item malformado nao vira reprovacao
            continue
        campo = rep.campo.strip()
        motivo = rep.motivo.strip()
        # Sem campo nao ha retry cirurgico; sem motivo o redator nao sabe o que
        # corrigir. Nos dois casos a "reprovacao" nao e acionavel.
        if not campo or not motivo:
            continue
        regra = rep.regra.strip()
        if regra not in REGRAS_CONHECIDAS:
            regra = f"{regra or 'sem-ancora'} (ancora nao reconhecida)"
        out.append({"campo": campo, "motivo": motivo, "regra": regra})
    return out, None


def _falha(
    erro: str, modelo: str, cost_usd: float = 0.0
) -> AuditarFichaResponse:
    """Falha de CHAMADA: nao auditada. Nem aprovada, nem reprovada.

    `auditor_enabled=false` e o ponto: e o mesmo estado que o stub do runner
    devolve, e o workflow ja o carrega ate o `persistir` — ninguem vai ler a
    ficha como auditada.
    """
    return AuditarFichaResponse(
        success=False,
        aprovado=False,
        auditor_enabled=False,
        modelo=modelo,
        reprovacoes=[],
        pendencias=[
            "auditor de ficha (S6) nao concluiu: " + erro + ". A ficha NAO foi "
            "auditada — passou apenas pelo validador deterministico (S5)."
        ],
        model=modelo,
        cost_usd=cost_usd,
        error=erro,
    )


async def auditar_ficha(
    request: AuditarFichaRequest | dict,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> AuditarFichaResponse:
    """Audita a ficha contra o dossie e o checklist do Livro.

    Nunca levanta: qualquer falha vira `success=false` + error, com
    `aprovado=false` e `auditor_enabled=false` (ver `_falha`).
    """
    if isinstance(request, dict):
        request = AuditarFichaRequest(**request)

    provider = provider or request.provider or DEFAULT_PROVIDER
    model = model or request.model or resolver_modelo()

    if not request.ficha_json:
        return _falha("nenhuma ficha para auditar", model)
    if not request.dossie:
        # Sem dossie nao ha contra o que conferir. Aprovar aqui seria o pior
        # resultado possivel: um "aprovado" que nao olhou nada.
        return _falha(
            "dossie vazio — sem fonte de verdade nao ha auditoria de fidelidade",
            model,
        )

    llm_provider = create_provider(provider)
    prompt = build_auditar_ficha_prompt(request)

    response: LLMResponse = await llm_provider.agenerate(
        prompt=prompt,
        model=model,
        temperature=0.0,  # conferencia e determinista; criatividade aqui e defeito
        response_mime_type="application/json",
        max_tokens=8192,
    )
    raw = response.text or ""
    used_model = response.model or model
    cost_usd = (response.metadata.get("cost_usd", 0.0) if response.metadata else 0.0)

    try:
        parsed = parse_llm_json(raw)
    except Exception as e:  # noqa: BLE001
        logger.warning("AUDITOR_FICHA_PARSE_FAIL: %r | head=%r", e, raw[:200])
        return _falha(f"parse do JSON do LLM falhou: {e}", used_model, cost_usd)

    reprovacoes, err = _normalizar_reprovacoes(parsed)
    if err is not None:
        logger.info("AUDITOR_FICHA_VALIDATION_FAIL: %s", err)
        return _falha(err, used_model, cost_usd)

    aprovado = not reprovacoes
    logger.info(
        "AUDITOR_FICHA_OK aprovado=%s reprovacoes=%d model=%s campos=%s",
        aprovado, len(reprovacoes), used_model,
        [r["campo"] for r in reprovacoes],
    )
    return AuditarFichaResponse(
        success=True,
        aprovado=aprovado,
        auditor_enabled=True,
        modelo=used_model,
        reprovacoes=reprovacoes,
        pendencias=[],
        model=used_model,
        cost_usd=cost_usd,
        error=None,
    )


__all__ = ["auditar_ficha", "resolver_modelo", "REGRAS_CONHECIDAS"]

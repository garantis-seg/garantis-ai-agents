"""ficha_writer agent — escreve os slots de texto de uma ficha (FichaJSON v2). Etapa S4.

Stateless. Usa o factory (provider default = Gemini) em JSON mode, sem schema
estático: os slots mudam por request. O modelo sai do papel `ficha_redacao` do shared.

Dois modos (ver `schemas.py`):

- **v4** (request com `esqueleto`): resolve os slots pelo Livro (`livro.py`), monta o
  prompt v4 (`prompts_v4.py`), valida a saída (`validacao.py`) e corrige em até
  `MAX_RODADAS` rodadas internas. Cada rodada pede só os slots que reprovaram e os
  alertas sem resposta. Depois de 3 rodadas com erro, devolve `success=false` com
  `erros[]` no formato `{campo, erro, valor_anterior}`.
- **v3** (request sem `esqueleto`): o comportamento antigo, sem mudança. Uma chamada,
  validação leve (presença e tipo string). O caller confere o `max`.
"""

import logging
from typing import Optional

from garantis_shared.llm_models import model_for

from ...providers import create_provider
from ...providers.base import LLMResponse
from ...utils.llm_json import parse_llm_json
from .livro import SlotResolvido, chave_livro, motivos_nao_aplicaveis, resolver_slots
from .prompts import PROMPT_VERSION, PROMPT_VERSION_V3, build_write_fields_prompt
from .prompts_v4 import build_prompt_v4
from .schemas import (
    AlertaRespondido,
    CampoSpec,
    ErroDeCampo,
    FichaWriteFieldsRequest,
    FichaWriteFieldsResponse,
)
from .validacao import (
    CAMPO_ALERTAS,
    avisos,
    origem_valor,
    processos_citaveis,
    processos_citaveis_brutos,
    renovacao_sem_corretor,
    validar_alertas,
    validar_campos,
)

logger = logging.getLogger(__name__)

DEFAULT_PROVIDER = "gemini"
DEFAULT_MODEL = model_for("ficha_redacao")

#: Rodadas internas do v4. 3, como o `MAX_TENTATIVAS` do redator do shared: a 2ª
#: rodada resolve quase todo estouro de limite (plano de 21/10/2026, S4).
MAX_RODADAS = 3


def _resolve_campos_alvo(
    request: FichaWriteFieldsRequest,
) -> tuple[Optional[list[CampoSpec]], Optional[str]]:
    """Os slots ALVO da chamada.

    Sem campos_com_erro: todos os request.campos. Com campos_com_erro (retry): SÓ os
    slots com erro, na ordem de campos_com_erro, com os specs de request.campos. Um nome
    com erro sem spec é contrato quebrado pelo caller.
    """
    if not request.campos_com_erro:
        return list(request.campos), None
    by_nome = {c.nome: c for c in request.campos}
    alvo: list[CampoSpec] = []
    for ce in request.campos_com_erro:
        spec = by_nome.get(ce.nome)
        if spec is None:
            return None, f"campo_com_erro '{ce.nome}' sem spec correspondente em `campos`"
        alvo.append(spec)
    return alvo, None


def _extract_and_validate(
    parsed: dict, campos: list[CampoSpec]
) -> tuple[Optional[dict[str, str]], Optional[str]]:
    """v3: extrai EXATAMENTE os slots pedidos, exigindo string. Não confere `max`."""
    out: dict[str, str] = {}
    for spec in campos:
        if spec.nome not in parsed:
            return None, f"campo ausente na resposta do LLM: '{spec.nome}'"
        val = parsed[spec.nome]
        if not isinstance(val, str):
            return None, f"campo '{spec.nome}' deveria ser string, veio {type(val).__name__}"
        out[spec.nome] = val
    return out, None


async def _chamar(llm_provider, prompt: str, model: str) -> LLMResponse:
    return await llm_provider.agenerate(
        prompt=prompt,
        model=model,
        temperature=0.0,
        response_mime_type="application/json",  # JSON mode SEM schema estático (slots dinâmicos)
        thinking_budget=0,
        max_tokens=8192,
    )


def _custo(response: LLMResponse) -> float:
    return float(response.metadata.get("cost_usd", 0.0)) if response.metadata else 0.0


# ── v3 (compat) ───────────────────────────────────────────────────────────


async def _write_v3(request: FichaWriteFieldsRequest, provider: str, model: str):
    campos_alvo, err = _resolve_campos_alvo(request)
    if err is not None:
        return FichaWriteFieldsResponse(
            success=False, campos={}, model=model, cost_usd=0.0, error=err,
            prompt_version=PROMPT_VERSION_V3,
        )

    llm_provider = create_provider(provider)
    prompt = build_write_fields_prompt(request, campos_alvo=campos_alvo)
    response: LLMResponse = await _chamar(llm_provider, prompt, model)
    raw = response.text or ""
    used_model = response.model or model
    cost_usd = _custo(response)

    try:
        parsed = parse_llm_json(raw)
    except (ValueError, Exception) as e:  # noqa: BLE001
        logger.warning("FICHA_WRITER_PARSE_FAIL: %r | head=%r", e, raw[:200])
        return FichaWriteFieldsResponse(
            success=False, campos={}, model=used_model, cost_usd=cost_usd,
            error=f"parse do JSON do LLM falhou: {e}", prompt_version=PROMPT_VERSION_V3,
        )

    campos, err = _extract_and_validate(parsed, campos_alvo)
    if err is not None:
        logger.info("FICHA_WRITER_VALIDATION_FAIL: %s", err)
        return FichaWriteFieldsResponse(
            success=False, campos={}, model=used_model, cost_usd=cost_usd, error=err,
            prompt_version=PROMPT_VERSION_V3,
        )
    return FichaWriteFieldsResponse(
        success=True, campos=campos, model=used_model, cost_usd=cost_usd, error=None,
        prompt_version=PROMPT_VERSION_V3,
    )


# ── v4 ────────────────────────────────────────────────────────────────────


async def _write_v4(request: FichaWriteFieldsRequest, provider: str, model: str):
    chave = chave_livro(request)
    campos_alvo, err = _resolve_campos_alvo(request)
    if err is not None:
        return FichaWriteFieldsResponse(
            success=False, model=model, error=err, prompt_version=PROMPT_VERSION,
            tipo_livro=chave,
        )
    slots, nao_aplicaveis = resolver_slots(request, campos_alvo)
    motivos = motivos_nao_aplicaveis(chave, nao_aplicaveis)
    avisos_req = avisos(request, chave, slots)
    origem = origem_valor(request)
    sem_corretor = renovacao_sem_corretor(request, chave)
    citaveis = processos_citaveis(request)
    citaveis_txt = processos_citaveis_brutos(request)

    # Rodada 1: o retry externo (campos_com_erro do caller) entra como erro conhecido.
    erros_retry: list[ErroDeCampo] = [
        ErroDeCampo(campo=c.nome, erro=c.erro, valor_anterior=c.valor_anterior)
        for c in (request.campos_com_erro or [])
    ]
    pendentes_slots: list[SlotResolvido] = list(slots)
    pendentes_alertas = list(request.alertas)
    aprovados: dict[str, str] = {}
    respondidos: dict[str, AlertaRespondido] = {}
    erros: list[ErroDeCampo] = []
    cost_total = 0.0
    used_model = model
    rodada = 0

    if not slots and not pendentes_alertas:
        return FichaWriteFieldsResponse(
            success=True, model=model, prompt_version=PROMPT_VERSION, tipo_livro=chave,
            campos_nao_aplicaveis=nao_aplicaveis, motivos_nao_aplicaveis=motivos,
            avisos=avisos_req,
        )

    llm_provider = create_provider(provider)
    for rodada in range(1, MAX_RODADAS + 1):
        prompt = build_prompt_v4(
            request, chave=chave, slots=pendentes_slots, alertas=pendentes_alertas,
            citaveis=citaveis_txt, erros_retry=erros_retry, aprovados=aprovados,
        )
        response: LLMResponse = await _chamar(llm_provider, prompt, model)
        used_model = response.model or used_model
        cost_total += _custo(response)
        raw = response.text or ""
        try:
            parsed = parse_llm_json(raw)
        except (ValueError, Exception) as e:  # noqa: BLE001
            logger.warning("FICHA_WRITER_V4_PARSE_FAIL rodada=%s: %r | head=%r",
                           rodada, e, raw[:200])
            erros = [ErroDeCampo(campo="_saida", erro=f"parse do JSON do LLM falhou: {e}")]
            erros_retry = erros
            continue

        ok, erros_campos = validar_campos(parsed, pendentes_slots, citaveis,
                                          origem_valor=origem, sem_corretor=sem_corretor)
        ok_alertas, erros_alertas = validar_alertas(parsed, pendentes_alertas)
        aprovados.update(ok)
        respondidos.update({a.codigo: a for a in ok_alertas})
        erros = erros_campos + erros_alertas
        if not erros:
            break
        logger.info("FICHA_WRITER_V4 rodada=%s erros=%s", rodada, [e.campo for e in erros])
        com_erro = {e.campo for e in erros_campos}
        if "_saida" in com_erro:
            pendentes_slots = [s for s in pendentes_slots if s.nome not in ok]
        else:
            pendentes_slots = [s for s in pendentes_slots if s.nome in com_erro]
        pendentes_alertas = [a for a in pendentes_alertas if a.codigo not in respondidos]
        erros_retry = erros

    alertas_ordenados = [respondidos[a.codigo] for a in request.alertas if a.codigo in respondidos]
    if erros:
        resumo = "; ".join(f"{e.campo}: {e.erro}" for e in erros)
        return FichaWriteFieldsResponse(
            success=False, campos=aprovados, model=used_model, cost_usd=round(cost_total, 6),
            error=f"validação falhou após {rodada} rodada(s): {resumo}",
            prompt_version=PROMPT_VERSION, tipo_livro=chave,
            alertas_respondidos=alertas_ordenados, erros=erros, rodadas=rodada,
            campos_nao_aplicaveis=nao_aplicaveis, motivos_nao_aplicaveis=motivos,
            avisos=avisos_req,
        )
    # Os slots ficam na ordem do request.
    campos = {s.nome: aprovados[s.nome] for s in slots if s.nome in aprovados}
    return FichaWriteFieldsResponse(
        success=True, campos=campos, model=used_model, cost_usd=round(cost_total, 6),
        prompt_version=PROMPT_VERSION, tipo_livro=chave,
        alertas_respondidos=alertas_ordenados, rodadas=rodada,
        campos_nao_aplicaveis=nao_aplicaveis, motivos_nao_aplicaveis=motivos,
        avisos=avisos_req,
    )


async def write_ficha_fields(
    request: FichaWriteFieldsRequest | dict,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> FichaWriteFieldsResponse:
    """Escreve os slots de texto pedidos. Nunca levanta por erro do LLM: devolve
    `success=false` e o erro, com `model` e `cost_usd` propagados."""
    if isinstance(request, dict):
        request = FichaWriteFieldsRequest(**request)
    provider = provider or request.provider or DEFAULT_PROVIDER
    model = model or request.model or DEFAULT_MODEL
    if request.modo_v4:
        return await _write_v4(request, provider, model)
    return await _write_v3(request, provider, model)


__all__ = ["MAX_RODADAS", "write_ficha_fields", "CAMPO_ALERTAS"]

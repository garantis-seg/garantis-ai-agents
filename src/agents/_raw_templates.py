"""Templates CRUS dos prompts engine v6 (L1 mov/day + L2 + L3).

Objetivo: expor o ESQUELETO de cada prompt — instrucoes/regras estaticas —
SEM os dados do caso, com `{{campo}}` no lugar de cada injecao. Consumido pela
aba "Prompt Raw" do debug-llm no garantis-app (via proxy no frontend-api).

Estrategia ZERO-DRIFT: NAO duplicamos o texto dos prompts aqui. Em vez disso
chamamos os PROPRIOS builders (`build_*_prompt`) alimentados com inputs-
sentinela cujos campos string sao `"{{campo}}"`. Assim toda a parte estatica
(regras_criticas, instrucoes por campo, regras de ouro, etc.) sai byte-
identica do builder de producao — se o prompt mudar, este template muda junto.

Limitacoes conhecidas (cosmeticas, nao afetam a parte estatica):
- Campos numericos/bool nao viram `{{...}}` (quebrariam f"{x:,.0f}") — passam
  None e a linha correspondente some.
- Contadores de lista mostram "1 total" (1 row sentinela) em vez de "{{N}}".
- L2/L3 sao dispatch por `tipo_judicial`: o template renderiza UMA variante
  (civel pra L2, misto pra L3). A UI avisa que fiscal/trabalhista trocam esse
  bloco. As instrucoes universais (90% do prompt) nao variam.

Chaves do dict = `layer` canonico de `leads.engine_llm_calls` (espelha as
constantes LAYER_* do MeritoDebugTab no front).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _mov_factsheet_template() -> str:
    from .mov_factsheet.prompts import build_mov_factsheet_prompt
    from .mov_factsheet.schemas import (
        DocAnexado,
        FallbackContext,
        MovInput,
        ProcessoContext,
    )

    processo = ProcessoContext(
        cnj="{{cnj}}",
        classe="{{classe}}",
        polo_ativo="{{polo_ativo}}",
        polo_passivo="{{polo_passivo}}",
    )
    mov = MovInput(
        mov_id="{{mov_id}}",
        data="{{data}}",
        tipo="{{tipo_origem}}",
        texto="{{texto_da_publicacao}}",
    )
    # 1 doc sentinela renderiza o bloco DOCUMENTOS ANEXADOS; fallback_context
    # renderiza os blocos RESUMO DO PROCESSO + MOV ANTERIOR (sao independentes
    # de has_docs no builder).
    docs = [
        DocAnexado(
            doc_key="{{doc_key}}",
            titulo="{{titulo}}",
            tipo="{{tipo}}",
            data_documento="{{data_documento}}",
            text_content="{{texto_do_documento}}",
            provider="{{provider}}",
        )
    ]
    fb = FallbackContext(
        processo_resumo_ia="{{resumo_ia_do_processo}}",
        mov_anterior_resumo="{{resumo_da_mov_anterior}}",
        mov_anterior_categoria="{{categoria_mov_anterior}}",
    )
    return build_mov_factsheet_prompt(processo, mov, docs, fb)


# _day_factsheet_template REMOVIDO em 2026-06-13 (teardown do tier por-dia,
# decisao Elton): agent day_factsheet aposentou; o registry nao pode manter
# a entry (lazy import quebraria a rota GET /prompts em runtime).


def _processo_synthesis_template() -> str:
    from .processo_synthesis.prompts import (
        build_probabilidade_exito_prompt,
        build_processo_synthesis_prompt,
    )
    from .processo_synthesis.schemas import (
        ApoliceContextMin,
        MovFactSheetMin,
        ProcessoSynthesisRequest,
    )

    # tipo_judicial eh Literal — nao pode ser "{{...}}". Renderizamos a variante
    # 'civel' (default). Instrucoes universais nao mudam; soh o bloco TIPO-
    # SPECIFIC + matriz Daycoval. A UI avisa que fiscal/trabalhista trocam isso.
    req = ProcessoSynthesisRequest(
        processo_numero="{{processo_numero}}",
        classe="{{classe}}",
        polo_ativo="{{polo_ativo}}",
        polo_passivo="{{polo_passivo}}",
        tipo_judicial="civel",
        mov_factsheets=[
            MovFactSheetMin(
                mov_id="{{mov_id}}",
                data="{{data}}",
                resumo_ato="{{resumo_ato}}",
                categoria="{{categoria}}",
                relevancia_merito="{{relevancia_merito}}",
            )
        ],
        apolices=[
            ApoliceContextMin(
                numero_apolice="{{numero_apolice}}",
                seguradora="{{seguradora}}",
            )
        ],
    )
    synthesis = build_processo_synthesis_prompt(req)
    prob_exito = build_probabilidade_exito_prompt(req)
    return (
        synthesis
        + "\n\n"
        + "=" * 78
        + "\n=== PROMPT 2/2 — PROBABILIDADE DE EXITO (Matriz Daycoval, call separada) ===\n"
        + "=" * 78
        + "\n\n"
        + prob_exito
    )


def _merito_synthesis_template() -> str:
    from .merito_synthesis.prompts import build_merito_synthesis_prompt
    from .merito_synthesis.schemas import (
        AIIMCardMin,
        CDACardMin,
        MeritoSynthesisRequest,
        PreviousSnapshot,
        ProcessoSynthesisMin,
        TomadorCardMin,
    )

    # tipo_judicial dos processos = None -> _determine_tipo_dominante retorna
    # 'misto' (variante generica). merito_id eh int (nao aceita {{}}) — fica 0.
    req = MeritoSynthesisRequest(
        merito_id=0,
        titulo="{{titulo}}",
        tipo_principal="{{tipo_principal}}",
        cnpj_principal="{{cnpj_principal}}",
        razao_social="{{razao_social}}",
        processo_syntheses=[
            ProcessoSynthesisMin(
                processo_numero="{{processo_numero}}",
                classe="{{classe}}",
                estado_processual="{{estado_processual}}",
                risco_processo_intermediario="{{risco_processo_intermediario}}",
            )
        ],
        cdas=[
            CDACardMin(
                cda_number="{{cda_number}}",
                tipo_tributo="{{tipo_tributo}}",
                ente="{{ente}}",
            )
        ],
        aiims=[
            AIIMCardMin(
                tipo="{{tipo}}",
                numero="{{numero}}",
                relacao="{{relacao}}",
            )
        ],
        tomador=TomadorCardMin(nome="{{nome_tomador}}", cnpj_basico="{{cnpj_basico}}"),
        previous_snapshot=PreviousSnapshot(
            risco_anterior="{{risco_anterior}}",
            classified_at_anterior="{{classified_at}}",
        ),
    )
    return build_merito_synthesis_prompt(req)


# layer canonico (engine_llm_calls.layer) -> builder do template cru.
_BUILDERS = {
    "layer1_mov_factsheet": _mov_factsheet_template,
    "layer2_processo_synthesis": _processo_synthesis_template,
    "layer3_merito_synthesis": _merito_synthesis_template,
}


def get_raw_prompt_templates() -> dict[str, str]:
    """Retorna {layer: template_cru}. Cada builder eh isolado em try/except —
    falha de um nao derruba os outros (o layer afetado vira string de erro)."""
    out: dict[str, str] = {}
    for layer, builder in _BUILDERS.items():
        try:
            out[layer] = builder()
        except Exception as e:  # pragma: no cover - defensivo
            logger.exception("raw template build falhou: layer=%s", layer)
            out[layer] = f"[erro ao gerar template cru de {layer}: {e!r}]"
    return out


__all__ = ["get_raw_prompt_templates"]

"""Mov FactSheet Agent — engine v6_meritos camada 1.

Single LLM call por movimentacao, extrai 13 campos estruturados.
Substitui mov_summarizer durante coexistencia (kind='mov_factsheet' vs kind='movimentacao').
"""

import json
import logging
import os
from typing import Optional

from ...providers import create_provider
from ...providers.base import LLMResponse
from ...utils.llm_json import parse_llm_json
from .._utils import MODEL_VARIANT_TEXT, call_l1_with_vision_fallback
from .._utils.feature_flags import flag_enabled
from .prompts import build_mov_factsheet_prompt
from .fundacao import derivar_categoria, derivar_status_garantia
from .schemas import (
    DocAnexado,
    FallbackContext,
    MovFactSheetCard,
    MovInput,
    ProcessoContext,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.getenv("MOV_FACTSHEET_MODEL", "gemini-2.5-flash-lite")
DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER", "gemini")

# Bump quando alterar build_mov_factsheet_prompt OR MovFactSheetCard schema.
# Usado pra drift detection em leads.engine_llm_calls.prompt_version.
#
# v2.0 (2026-05-25, P1 do prompt-engineering FINDINGS):
#   - Removido bloco FORMATO DE SAIDA do prompt (duplicava response_schema).
#   - Enriquecido Field(description=...) em schemas.py com semantica que vivia
#     no prompt. Cada campo carrega sua propria guidance via JSON Schema.
#   - Schema enforcement Gemini cobre estrutura. Prompt cobre semantica do
#     dominio + regras criticas (POLOS, RECURSOS, EXTINCAO).
#
# v2.1 (2026-05-25, P2 do prompt-engineering FINDINGS):
#   - REGRA DE LEITURA DE POLOS + REGRA RECURSOS + REGRA EXTINCAO movidas do
#     meio pro TOPO em <regras_criticas> XML. Combate Lost-in-the-Middle.
#   - <lembrete_final> no fim como recency anchor pras 3 regras criticas.
#   - Eliminado bloco duplicado "REGRA DURA EXTINCAO" dentro de INSTRUCOES POR
#     CAMPO (single source of truth: <regra_extincao_sem_merito>).
#
# v2.2 (2026-05-25, polo-regression suite detectou contradicao L1 vs L2):
#   - <regra_extincao_sem_merito> ENRIQUECIDA com EXCECAO Tomador-AUTOR.
#     Antes L1 sempre forçava sentido='neutro' em extincao_sem_merito. MAS L2
#     prompt v2.2 ja tinha <regra_extincao_tomador_autor> dizendo o OPOSTO
#     pra classes Tomador-autor (Anulatoria/MS/Tutela Cautelar Antecedente/
#     Embargos): sentido='desfavoravel'. Resultava em contradicao silenciosa
#     onde card L1 marcava neutro e L2 corrigia pra desfavoravel.
#   - Fix: L1 agora aplica mesma regra que L2 — DEFAULT neutro pra classes
#     Tomador-reu, EXCECAO desfavoravel pra classes Tomador-autor. Caso
#     paradigma: Tutela Cautelar Antecedente extinta por perda de objeto
#     (CPC 308) = sentido='desfavoravel' (Tomador perdeu).
#
# v2.3 (2026-05-25, polo-regression case 6 LLM confundia natureza):
#   - REGRA DURA — INEXIGIBILIDADE NAO eh EXTINCAO SEM MERITO. Quando
#     sentenca em Embargos/Anulatoria acolhe tese e declara "inexigibilidade
#     do credito" => natureza='procedente' (NAO extinto_sem_merito), porque
#     foi julgamento de merito que acolheu a tese. Distincao chave: extincao
#     da EF correlata como CONSEQUENCIA da procedencia eh efeito reflexo,
#     nao transforma a sentenca em extinto_sem_merito.
# v3 (2026-06-04, integração L1 v7): fundação resolvida no prompt (Tomador no polo /
#   infere grupo econômico), taxonomia tipo_doc(34) substitui categoria (derivada por
#   código), evento_garantia.numero_apolice, bug "extincao SEMPRE neutro" corrigido
#   (condicional ao polo), classe 1A-1D (órfão tratado), resumo proporcional, E as
#   CIRURGIAS do POC validado (fundacao.py): TRAVA_DECISAO (mero expediente ≠ decisão;
#   acionamento=risco máximo), REGRA_TITULARIDADE (verbo de resultado sem dono→neutro),
#   MODULO_TRABALHISTA (condicional; TST≠stj; Tomador pode ser reclamante). v2.3 PURO
#   reprovou (memory l1-teste-reprova) — estas cirurgias são as melhorias comprovadas.
#   Ver memory l1-fase-b-decisao-v3 / l1-invariante-fundacao.
#
# v3.1 (2026-06-09, L1 DS cleanup — Lote 1): removidos campos MORTOS do schema
#   (= response_schema do Gemini): 'apolice' (ApoliceBlock — redundante com
#   evento_garantia + o card autoritativo kind='apolice') e 'proximos_passos'
#   (sem consumidor; a UI mostra proximos_passos_provaveis, campo da L3, NAO este).
#   'processos_conexos_mencionados' SUPRIMIDO via prompt (campo mantido no schema;
#   re-ligado gated na peticao inicial no Lote 3 / FASE 4). tipo_garantia NAO
#   mexido aqui — sera REALOCADO pra dentro de evento_garantia no Lote 2.
#   Asserts do eval nao tocam nenhum campo removido/suprimido. Decisao Elton 2026-06-09.
PROMPT_VERSION = "mov_factsheet.v3.1"

# FASE 2 redesign L1 — caminho v4 (fatos neutros + derivacoes) sob flag, default OFF.
# Flag ON => a LLM emite SO fatos neutros (schemas_v4) com prompt neutro (prompts_v4);
# sentido/categoria/status/peca_pivo viram DERIVED (garantis_shared.derivacoes). Shadow:
# coexiste com v3.1 (default), nada de prod muda ate o flip (F1). Ver
# ~/.claude/plans/l1-fase2-kickoff-2026-06-09.md.
L1_NEUTRAL_FLAG = "L1_NEUTRAL_ENABLED"


def _build_card_v4(parsed: dict, mov: "MovInput", card_cls=None) -> dict:
    """Caminho v4 (fatos neutros): valida o card, injeta identidade pos-parse (mov_id/data
    NAO sao emitidos pela LLM — ficam fora do response_schema) e aplica os derivados
    sujeito-INDEPENDENTES no ponto comum G6 (categoria/status_garantia/relevante/peca_pivo).
    sentido/delta_risco NAO entram no card — sao parte_seguravel-dependentes, computados
    on-read na Fase 3.

    card_cls: classe de validacao do ramo (default MovFactSheetCardV4; o ramo PETICAO
    passa PeticaoExtractCardV4 — superset; validar com a base DROPARIA cdas/citados).

    Imports lazy: schemas_v4 + garantis_shared.derivacoes so sao tocados sob flag, pra o
    caminho v3.1 default nunca depender do shared pin novo (derivacoes ainda nao publicado
    no wheel). Ver ordem de deploy: publish shared -> bump pin -> flip flag."""
    from .schemas_v4 import MovFactSheetCardV4
    from garantis_shared.engine_v6.layer1_mov_factsheet.derivacoes import (
        aplicar_derivados_sujeito_indep,
    )

    card = (card_cls or MovFactSheetCardV4)(**parsed)  # valida; pydantic descarta extras
    card_data = card.model_dump()
    card_data["mov_id"] = mov.mov_id             # identidade injetada (nao LLM-emitida)
    if mov.data:
        card_data["data"] = mov.data
    aplicar_derivados_sujeito_indep(card_data)   # G6: categoria/status/relevante/peca_pivo (in-place)
    return card_data


async def classify_mov_factsheet(
    processo: ProcessoContext | dict,
    mov: MovInput | dict,
    documentos_anexados: list[DocAnexado | dict] | None = None,
    fallback_context: FallbackContext | dict | None = None,
    model: Optional[str] = None,
    provider: str = DEFAULT_PROVIDER,
    classe: Optional[str] = None,
) -> dict:
    """Extract a 13-field FactSheet from a single mov.

    Args:
        processo: contexto minimo (CNJ, classe, polos)
        mov: id + data + tipo + texto da publicacao (snippet DJe)
        documentos_anexados: docs vinculados a essa mov (rota com doc text)
        fallback_context: passado SOMENTE quando documentos_anexados vazio
        model: override Gemini model
        provider: 'gemini' (default)

    Returns:
        {"card": MovFactSheetCard.model_dump() | error_dict,
         "raw_response": str,
         "llm_raw_prompt": str,
         "usage": dict}
    """
    if isinstance(processo, dict):
        processo = ProcessoContext(**processo)
    if isinstance(mov, dict):
        mov = MovInput(**mov)

    docs_typed: list[DocAnexado] = []
    for d in documentos_anexados or []:
        docs_typed.append(d if isinstance(d, DocAnexado) else DocAnexado(**d))

    fb_typed: FallbackContext | None = None
    if fallback_context is not None:
        fb_typed = (
            fallback_context
            if isinstance(fallback_context, FallbackContext)
            else FallbackContext(**fallback_context)
        )

    if model is None:
        model = DEFAULT_MODEL

    use_v4 = flag_enabled(L1_NEUTRAL_FLAG)
    prompt_version = PROMPT_VERSION

    llm_provider = create_provider(provider)

    if use_v4:
        # Caminho neutro (Fase 2): prompt + response_schema v4, imports lazy (isolam o
        # caminho v3.1 default do shared pin novo). Mesmo envelope de input (processo/
        # mov/docs/fallback/classe) — so o card emitido muda.
        from .prompts_v4 import build_mov_factsheet_prompt_v4
        from .schemas_v4 import (
            MovFactSheetCardV4,
            PeticaoExtractCardV4,
            DOC_INCERTO_PROMPT_VERSION,
    PETICAO_PROMPT_VERSION,
            PROMPT_VERSION_V4,
        )

        prompt_version = PROMPT_VERSION_V4
        prompt = build_mov_factsheet_prompt_v4(
            processo, mov,
            documentos_anexados=docs_typed,
            fallback_context=fb_typed,
            classe=classe,
        )
        response_schema = MovFactSheetCardV4
        if classe == "peticao":
            # Ramo PETICAO (peticao_extract.v1, FASE 4): schema SUPERSET (card v4 +
            # cdas/processos_citados) e versao POR RAMO — bump da peticao nao invalida
            # cache do mov_factsheet e vice-versa. Opt-in do caller; prod nunca envia.
            prompt_version = PETICAO_PROMPT_VERSION
            response_schema = PeticaoExtractCardV4
        elif classe == "doc_incerto":
            # Ramo 1X (doc_incerto_extract.v1): fallback do identify — doc do 1o dia
            # sem tipo confirmado. MESMO schema superset; a prompt CLASSIFICA o tipo
            # em vez de crava-lo. Draft aprovado Elton 2026-06-12.
            prompt_version = DOC_INCERTO_PROMPT_VERSION
            response_schema = PeticaoExtractCardV4
    else:
        prompt = build_mov_factsheet_prompt(
            processo, mov,
            documentos_anexados=docs_typed,
            fallback_context=fb_typed,
            classe=classe,
        )
        response_schema = MovFactSheetCard

    response: LLMResponse = await call_l1_with_vision_fallback(
        llm_provider,
        model=model,
        prompt=prompt,
        gcs_urls=[d.gcs_url for d in docs_typed if d.gcs_url],
        # GATE DE OCR (L1 v7): pares (text_content, gcs_url) por doc — o gate decide
        # por documento se manda pro Vision (texto-lixo OU pagina-imagem). Ver ocr_gate.
        docs_text=[(d.text_content, d.gcs_url) for d in docs_typed if d.gcs_url],
        response_schema=response_schema,
        log_label=f"mov_id={mov.mov_id}",
        thinking_budget=0,
    )

    raw_response = response.text
    try:
        parsed = parse_llm_json(raw_response)
        if use_v4:
            # v4: fatos neutros + derivados sujeito-independentes (G6). Identidade injetada
            # dentro do helper (mov_id/data fora do response_schema). Ramo peticao valida
            # com o superset (a base droparia cdas/processos_citados).
            card_data = _build_card_v4(
                parsed, mov,
                card_cls=response_schema if classe in ("peticao", "doc_incerto") else None,
            )
        else:
            # Echo input identifiers em caso de LLM reset
            parsed.setdefault("mov_id", mov.mov_id)
            if mov.data and not parsed.get("data"):
                parsed["data"] = mov.data
            if mov.tipo and not parsed.get("tipo_origem"):
                parsed["tipo_origem"] = mov.tipo
            # DERIVACAO POR CODIGO (L1 v7): o LLM emite tipo_doc(34) e evento_garantia.tipo;
            # categoria(14) e status_garantia_pos_mov sao DERIVADOS — fonte unica da verdade,
            # zero contradicao. ★ ARMADILHA #1: derivar ANTES de instanciar (categoria e lida
            # pela L2; se ficar None o sinal some). Ver memory l1-divida-categoria-tipodoc.
            if not parsed.get("categoria"):
                parsed["categoria"] = derivar_categoria(parsed.get("tipo_doc"))
            _eg_tipo = (parsed.get("evento_garantia") or {}).get("tipo")
            if not parsed.get("status_garantia_pos_mov") or parsed.get("status_garantia_pos_mov") == "nenhum":
                parsed["status_garantia_pos_mov"] = derivar_status_garantia(_eg_tipo)
            card = MovFactSheetCard(**parsed)
            card_data = card.model_dump()
    except (json.JSONDecodeError, Exception) as e:
        logger.error(f"mov_factsheet parse failed mov_id={mov.mov_id}: {repr(e)}")
        card_data = {"error": repr(e), "raw": raw_response, "mov_id": mov.mov_id}

    usage = {
        "input_tokens": response.input_tokens or 0,
        "output_tokens": response.output_tokens or 0,
        "total_tokens": (response.input_tokens or 0) + (response.output_tokens or 0),
        "cost_usd": (response.metadata.get("cost_usd", 0.0) if response.metadata else 0.0),
        "model": model,
        "provider": provider,
        "model_variant": (
            response.metadata.get("model_variant", MODEL_VARIANT_TEXT)
            if response.metadata else MODEL_VARIANT_TEXT
        ),
    }

    return {
        "card": card_data,
        "raw_response": raw_response,
        "llm_raw_prompt": prompt,
        "prompt_version": prompt_version,
        "usage": usage,
    }

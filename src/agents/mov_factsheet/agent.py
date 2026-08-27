"""Mov FactSheet Agent — engine v6_meritos camada 1.

Single LLM call por movimentacao, extrai 13 campos estruturados.
Substitui mov_summarizer durante coexistencia (kind='mov_factsheet' vs kind='movimentacao').
"""

import hashlib
import json
import logging
import os
from typing import Optional

from garantis_shared.llm_chunking import map_reduce_classify

from ...providers import create_provider
from ...providers.base import LLMResponse
from ...utils.llm_json import parse_llm_json
from .._utils import (
    MODEL_VARIANT_TEXT,
    MODEL_VARIANT_VISION,
    call_l1_with_vision_fallback,
    seed_for,
)
from .._utils.feature_flags import flag_enabled
from .chunking import reduce_peca_cards, split_large_peca_variants
from .prompts import build_mov_factsheet_prompt
from .fundacao import derivar_categoria, derivar_status_garantia
from .schemas import (
    DocAnexado,
    DocGate,
    FallbackContext,
    MovFactSheetCard,
    MovInput,
    ProcessoContext,
)

logger = logging.getLogger(__name__)

# Frases EN que NUNCA aparecem num resumo_ato legitimo (PT) — assinaturas das 2 formas
# de degeneracao do Gemini observadas em prod (2026-06-29): (a) o modelo vaza o proprio
# meta-erro de JSON ("The JSON was not valid... Here is the schema again"); (b) o modelo
# quebra a meio e RE-ESCREVE o resumo em ingles ("The process has been concluded. This is
# a routine administrative action..."). Em ambas o JSON e VALIDO e o schema (resumo_ato:
# str) aceita -> ia cru pro card e poluia a timeline. Set tight p/ zero falso-positivo.
_RESUMO_META_LEAK_MARKERS = (
    "the json", "valid json", "json should", "schema again", "wrapped in markdown",
    "control characters", "the process has been", "this is a routine",
    "does not involve", "does not mention", "in the;",
)


def _resumo_looks_like_json_meta_leak(resumo) -> bool:
    """True se o resumo_ato carrega assinatura de degeneracao (meta-JSON ou EN). Match
    por substring lowercase contra _RESUMO_META_LEAK_MARKERS."""
    if not isinstance(resumo, str):
        return False
    low = resumo.lower()
    return any(m in low for m in _RESUMO_META_LEAK_MARKERS)

DEFAULT_MODEL = os.getenv("MOV_FACTSHEET_MODEL", "gemini-3.1-flash-lite")  # 2026-06-26: upgrade 2.5->3.1 (2.5-flash-lite 503 high-demand). Elton.
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


# ══════════════════════════════════════════════════════════════════════════════
# TRAVA DE CORPO (2026-08-23, card 869ent0g8): sem CORPO e sem DOC ANEXO nao ha
# decisao — e ponto, sem passar pelo olho do LLM.
#
# O que a trava substitui: a instrucao ESTETICA de `prompts_v4.py` ("Snippet
# generico ... => tem_decisao=false"), que pede ao modelo um julgamento de gosto
# sobre a propria entrada. Ela falha por construcao quando o rotulo do catalogo do
# provider CONTEM as palavras do desfecho: "Julgado - Julgado improcedente o
# pedido" (39 chars, sem corpo, sem doc) nao e generico — e especifico e ERRADO,
# e ate o campo `dispositivo` (que exige o trecho literal) e satisfeito por ele,
# porque a frase esta mesmo la. Medido em prod: 3.964 cards de decisao nascidos
# assim, em 810 processos / 227 meritos (199 com apolice).
#
# A trava e MECANICA e usa so o que a funcao ja tem em maos — `mov.texto` e
# `documentos_anexados`. ⛔ NAO precisa do `metadata` do provider: medido, o campo
# `classificacao_automatica` do jusbrasil aparece em 49,1% das movs <=60 chars e em
# 37,1% das movs com >1.000 chars de texto REAL, e o `step_type` do judit em 64,1%
# x 48,4% — nenhum dos dois separa etiqueta de documento, e nenhum existe em
# tjsp_legacy/datalake/escavador.
#
# O CORTE em 60 chars e medido, nao escolhido: censo de 1.663 strings-fonte
# classificadas por 2 lentes independentes + desempate cego. Ate 60 chars, 96,1%
# dos cards vem de etiqueta de catalogo (2,6% texto real); na faixa 61-120 a
# etiqueta cai pra 68,8% e o texto real sobe pra 25,5%. O penhasco e 10x.
# ⛔ Nao suba o teto pra "pegar mais": a 120 a trava silenciaria 1 ato real em 4.
# ⚠️ TETO DECLARADO: sobram ~1.900 cards-etiqueta na faixa 61-120 que esta trava
# NAO alcanca. Pegar aquela faixa exige outro discriminador (voz do juiz /
# cardinalidade da string), nao um numero maior.
#
# ⚰️ Nasceu default OFF (apagar decisao fabricada move banda nos DOIS sentidos: 18
# meritos desceriam, 11 subiriam), foi LIGADA em prod em 2026-08-23 com OK do Elton e
# nao se moveu mais. A flag `L1_DECISAO_EXIGE_CORPO` saiu em 2026-08-27 (card 869entgbc).
# ⛔ O comportamento e o de HOJE — saiu a possibilidade de desligar, nao a trava.
#
# O corte mora em `prompts_v4.py` (fonte unica — o prompt tambem o le). Import LAZY,
# mesmo motivo do `schemas_v4`/`derivacoes` logo abaixo: o caminho v3.1 default nao
# pode passar a depender do modulo v4.


def _sem_corpo(mov: "MovInput", docs: list) -> bool:
    """A unidade nao tem sobre o que decidir. PURA (testavel sem LLM/banco).

    TRES estados, nao dois (869enu94n) — "lista de docs vazia" e ambiguo:

      1. ha doc admissivel                 -> False (o agent le o doc)
      2. NAO existe documento nenhum       -> True  (rotulo do provider sem lastro)
      3. existe doc e nao foi admitido     -> False (ponteiro pra peca que nao demos conta
                                                     de ler; apagar perderia fato REAL)

    O 3o caso e o que faltava. Ele custou o merito 17 (CVC, com apolice), cuja
    `decisao_atual` improcedente 2022-08-18 se apoia num card-rotulo cujo unico doc e uma
    `Sentenca Tipo A` com `has_text=false` E `gcs_url` NULL — a peca EXISTE, so nao chega
    aqui. Medido: 15 cards em 14 meritos. Raro, mas e o unico dos tres em que a trava
    erra, e erra na direcao perigosa (sub-rating).

    `docs_inadmissiveis` vem carimbado pelo loader do shared
    (`fetch_docs_for_movs_batch`). Ausente/0 = comportamento anterior.
    """
    from .prompts_v4 import CORPO_MIN_CHARS
    if getattr(mov, "docs_inadmissiveis", 0):
        return False
    return not docs and len((mov.texto or "").strip()) <= CORPO_MIN_CHARS


# Campos que so existem PORQUE ha decisao — caem juntos com ela (o proprio
# `_REGRAS_CRUS` ja diz "e entao natureza/recorrente/provido/resultado = null").
# `transito_certificado` fica de FORA de proposito: certidao de transito e um fato
# proprio, com guard proprio no L2, e nao depende de haver decisao nesta mov.
_CAMPOS_DA_DECISAO = (
    "natureza", "instancia", "dispositivo", "recorrente_polo", "provido",
    "requerente_polo", "resultado_interlocutorio", "motivo_extincao",
    "efeito_suspensivo", "instrumento_cautelar",
)


def _zerar_decisao(card_data: dict) -> None:
    """Zera o bloco `decisao` in-place. Roda ANTES de `aplicar_derivados_sujeito_indep`
    pra que categoria/peca_pivo/relevante saiam coerentes com tem_decisao=false.

    ⚠️ Chamada por DOIS predicados independentes (corpo e dispositivo) — por isso o nome
    e a acao, nao a razao. Idempotente: aplicar duas vezes e igual a aplicar uma.
    """
    d = card_data.get("decisao")
    if not isinstance(d, dict):
        return
    d["tem_decisao"] = False
    for k in _CAMPOS_DA_DECISAO:
        if k in d:
            d[k] = None


# ══════════════════════════════════════════════════════════════════════════════
# TRAVA DE DISPOSITIVO (card 869enpem7): sem a ANCORA, o L1 nao afirma decisao.
#
# ⛔ NAO e a irma da trava de corpo, e a OUTRA METADE. Sao dois predicados para a
# mesma conclusao, e nenhum contem o outro:
#   corpo       = "nao ha sobre o que decidir"  (a unidade nao tem texto nem doc)
#   dispositivo = "ha corpo e o card nao aponta onde"  (o card ADMITE que nao sustenta)
# O cohort residual desta trava e, por construcao, o que a de corpo NAO alcanca:
# card COM corpo, que afirma veredito e nao consegue citar a frase que o enuncia.
#
# ⭐ A regra JA EXISTE no prompt, palavra por palavra (`_REGRAS_CRUS`):
#   "Nao achou a frase no texto => dispositivo=null E tem_decisao=false".
# Ela e VIOLADA, nao mal escrita — por isso o conserto e MECANICO e nao mais uma
# frase no prompt. O bullet FICA: ele e o que faz o modelo emitir a ancora nos casos
# em que ele consegue, e e o controle positivo desta trava.
#
# ⛔ Default OFF. O custo declarado: decisao LEGITIMA que o modelo simplesmente nao
# soube citar cai junto (falso positivo de higiene virando perda de sinal). O numero
# medido e o dry-run estao no corpo do PR — nao ligue a flag sem eles.
L1_DECISAO_EXIGE_DISPOSITIVO = "L1_DECISAO_EXIGE_DISPOSITIVO"


def _decisao_exige_dispositivo() -> bool:
    """Flag da trava de dispositivo. Default OFF = card IDENTICO ao de hoje.

    ⛔ Mora AQUI, e nao em `prompts_v4.py` como o `L1_DECISAO_EXIGE_CORPO`: aquele tem
    DOIS consumidores (o prompt tambem o le, pra remover o anticorpo estetico) e por isso
    precisa de fonte unica no modulo folha. Este tem UM — o prompt nao muda sob ele.
    """
    return flag_enabled(L1_DECISAO_EXIGE_DISPOSITIVO)


def _sem_dispositivo(card_data: dict) -> bool:
    """O card AFIRMA decisao e nao consegue apontar a frase que decide. PURA.

    String vazia conta como ausente: o schema declara `None` como default, mas '' passa
    igual pela validacao e some do `IS NULL` da leitura — os dois significam a MESMA
    coisa ("nao achei a frase") e tem de cair no mesmo lado do predicado.
    """
    d = card_data.get("decisao")
    if not isinstance(d, dict) or not d.get("tem_decisao"):
        return False
    return not (d.get("dispositivo") or "").strip()


def _build_card_v4(parsed: dict, mov: "MovInput", card_cls=None, *,
                   sem_corpo: bool = False) -> dict:
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
    if sem_corpo:
        _zerar_decisao(card_data)                # ANTES do G6: peca_pivo sai coerente
    if _sem_dispositivo(card_data):
        # ⭐ O log sai com a flag DESLIGADA, de proposito — ele e a metade que MEDE.
        # A fase 0 deste card mediu 4 ocorrencias, todas de UM merito e UMA run: nao ha
        # volume pra decidir ligar. Um contador que so fala quando a trava age nunca
        # acumularia esse volume, e "contador em zero" seria indistinguivel de mudo.
        logger.warning(
            "L1_DECISAO_SEM_ANCORA mov_id=%s natureza=%s tipo_doc=%s travado=%s",
            mov.mov_id, (card_data.get("decisao") or {}).get("natureza"),
            card_data.get("tipo_doc"), _decisao_exige_dispositivo(),
        )
        if _decisao_exige_dispositivo():
            _zerar_decisao(card_data)            # idem — a ancora e a outra metade
    aplicar_derivados_sujeito_indep(card_data)   # G6: categoria/status/relevante/peca_pivo (in-place)
    return card_data


def _stub_ruido_card(
    mov: "MovInput", use_v4: bool, response_schema, classe: Optional[str]
) -> dict:
    """Card de baixa relevância pra quando o modelo devolve resposta VAZIA — doc
    ilegível (texto-lixo/OCR corrompido) ou safety-block. O mov foi LIDO (nada
    extraível), NÃO é um gap: evita o ciclo erro→500→5 retries→mov-falha→l1_degraded.
    Honesto: relevancia='ruido', tipo_doc='outros', sem decisão. Reusa o derivador G6.
    """
    stub = {
        "tipo_doc": "outros",
        "relevancia_merito": "ruido",
        "resumo_ato": (
            "Documento sem texto extraível (resposta vazia do modelo — "
            "provável OCR/texto corrompido)."
        ),
    }
    if use_v4:
        return _build_card_v4(
            stub, mov,
            card_cls=response_schema if classe in ("peticao", "doc_incerto") else None,
        )
    stub["mov_id"] = mov.mov_id
    if mov.data:
        stub["data"] = mov.data
    stub["categoria"] = derivar_categoria("outros")
    stub["status_garantia_pos_mov"] = derivar_status_garantia(None)
    return MovFactSheetCard(**stub).model_dump()


async def classify_mov_factsheet(
    processo: ProcessoContext | dict,
    mov: MovInput | dict,
    documentos_anexados: list[DocAnexado | dict] | None = None,
    fallback_context: FallbackContext | dict | None = None,
    model: Optional[str] = None,
    provider: str = DEFAULT_PROVIDER,
    classe: Optional[str] = None,
    documentos_gate: list[DocGate | dict] | None = None,
    _no_chunk: bool = False,
) -> dict:
    """Extract a 13-field FactSheet from a single mov.

    Args:
        processo: contexto minimo (CNJ, classe, polos)
        mov: id + data + tipo + texto da publicacao (snippet DJe)
        documentos_anexados: docs vinculados a essa mov (rota com doc text)
        documentos_gate: pares (text_content, gcs_url) POR DOCUMENTO pro gate de
            OCR/Vision, quando `documentos_anexados` traz o conjunto CONCATENADO
            num entry só (é o caso da petição). Ausente = o gate usa
            `documentos_anexados`, como sempre.
        fallback_context: passado SOMENTE quando documentos_anexados vazio
        model: override Gemini model
        provider: 'gemini' (default)

    Returns:
        {"card": MovFactSheetCard.model_dump() | error_dict,
         "raw_response": str,
         "llm_raw_prompt": str,
         "usage": dict,
         "vision_gate": dict}
    """
    if isinstance(processo, dict):
        processo = ProcessoContext(**processo)
    if isinstance(mov, dict):
        mov = MovInput(**mov)

    docs_typed: list[DocAnexado] = []
    for d in documentos_anexados or []:
        docs_typed.append(d if isinstance(d, DocAnexado) else DocAnexado(**d))

    # Pares do GATE. Por default são os próprios docs anexados (path do mov: 1
    # entry por doc). A petição manda o conjunto CONCATENADO num entry só — pro
    # PROMPT não mudar — e o par real vem aqui: sem isto o gate julgaria o texto
    # de N documentos somado contra o gcs_url de UM (o primário), que no caso
    # Steel é o AGRAVO, não a petição. Ver `documentos_gate`.
    gate_typed: list[DocGate] = [
        g if isinstance(g, DocGate) else DocGate(**g) for g in documentos_gate or []
    ]
    # 3º elemento = `so_capa` (o caller já identificou a peça e o texto é só a capa).
    # Tupla de 3 só no ramo do `documentos_gate`: o fallback por `documentos_anexados`
    # não tem como saber isso, e o helper aceita as duas aridades.
    gate_pairs: list[tuple] = (
        [(g.text_content, g.gcs_url, g.so_capa) for g in gate_typed if g.gcs_url]
        if gate_typed
        else [(d.text_content, d.gcs_url) for d in docs_typed if d.gcs_url]
    )
    gate_urls: list[str] = (
        [g.gcs_url for g in gate_typed if g.gcs_url]
        if gate_typed
        else [d.gcs_url for d in docs_typed if d.gcs_url]
    )
    vision_gate: dict = {}
    prompt_vision: Optional[str] = None

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

    # CHUNK GATE (v4): peça grande (>CHUNK_SIZE) estoura o L1 (Gemini >60s →
    # TIMEOUT_LAYER1_S). Split em chunks, classifica cada um em PARALELO e reduz por
    # campo (lê COMPLETO sem timeout). Evidência já vai head+tail no prompt builder; só
    # peça precisa. Recursa com _no_chunk=True (cada chunk <CHUNK_SIZE → 1 call normal).
    if use_v4 and not _no_chunk:
        variants = split_large_peca_variants(docs_typed)
        if variants:
            return await _classify_chunked(
                processo, mov, variants, fb_typed, model, provider, classe,
                gate_typed,
            )

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
        if classe in ("peticao", "doc_incerto") and gate_urls:
            # STEERING DOS ANEXOS (v1.5): 2ª versão do MESMO prompt, com o parágrafo que
            # declara os PDFs. Quem escolhe é o helper — só o ramo Vision a usa, e só
            # depois que o gate de fato mandou PDF. Aqui só se sabe que há CANDIDATO
            # (`gate_urls`), e candidato não é anexo: o gate ainda pode dizer que todo
            # doc é alcançável por texto. Montar as duas é 1 concat de string; deixar o
            # helper remontar prompt seria dar conhecimento de agent pra ele.
            prompt_vision = build_mov_factsheet_prompt_v4(
                processo, mov,
                documentos_anexados=docs_typed,
                fallback_context=fb_typed,
                classe=classe,
                pdfs_anexados=True,
            )
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

    # Seed determinístico (mov + prompt) — o MESMO padrão de L2/L3
    # (processo_synthesis/merito_synthesis), que faltava no L1. Gated em
    # ENGINE_LLM_SEED_ENABLED; `None` (flag OFF) é no-op no provider.
    #
    # POR QUE no L1: `temperature=0.0` NÃO é determinismo — o Gemini a temp=0 sem
    # seed tem micro-ruído de decode entre runs, e no L1 esse ruído não sai como
    # "outro fraseado": sai como OUTRO RÓTULO em campo enumerado. Medido em prod
    # (pn 0168886-31.2016.4.02.5101, doc providers.jusbrasil_autos_documents#770644):
    # dois cards a 3 SEGUNDOS de distância — 2232509 e 2232514, mesmo mov_id, mesmo
    # doc_id, mesma prompt_version v6.0, mesmo modelo — classificaram o MESMO número
    # administrativo como `paf` e como `pa`. Como `tipo` é metade da chave de
    # `leads.admin_items` (UNIQUE (tipo, numero_normalizado), write-once), essa
    # divergência não vira UPDATE: FORKA a entidade em dois nós permanentes.
    #
    # As `parts` do seed: `mov.mov_id` + o `prompt` inteiro. O `mov_id` é
    # REDUNDANTE POR CONSTRUÇÃO, não só "provadamente grátis": o
    # `build_mov_factsheet_prompt_v4` já embute o literal do mov_id DENTRO do
    # prompt (verificado executando os dois — trocar o mov_id muda o prompt), então
    # o prompt sozinho já discrimina E já estabiliza. Ele fica por simetria com o
    # padrão de L2/L3. O cohort confirma que incluí-lo não perde caso vivo: os
    # 52 de 52 pares (pn, número) discordantes vêm do MESMO mov_id E do MESMO
    # doc_id (0 com card nulo, 0 cross-mov, 0 cross-doc).
    # ⚠️ A redundância é CONDICIONAL ao prompt seguir embutindo o mov_id — e essa
    # dependência mora em `prompts_v4.py`, não aqui. Se o prompt parar de embuti-lo,
    # esta part deixa de ser decorativa e vira a ÚNICA coisa que separa leituras de
    # mov_ids diferentes. (A versão anterior deste comentário dizia o inverso — que
    # a part viraria o separador se o mesmo doc fosse lido sob mov_ids diferentes.
    # Não vira: nesse cenário o prompt já difere, e o seed já difere sem ela.)
    #
    # ⛔ Isto NÃO conserta a raiz (o rótulo dentro da chave) nem toca o prompt: é
    # redução de TAXA enquanto o N3 não entra. E `seed` é best-effort no Gemini —
    # trate como "mesma resposta na maior parte das vezes", nunca como garantia.
    seed = seed_for("mov_factsheet", mov.mov_id, prompt)

    response: LLMResponse = await call_l1_with_vision_fallback(
        llm_provider,
        model=model,
        prompt=prompt,
        gcs_urls=gate_urls,
        seed=seed,
        # GATE DE OCR (L1 v7): pares (text_content, gcs_url) por doc — o gate decide
        # por documento se manda pro Vision (texto-lixo OU pagina-imagem). Ver ocr_gate.
        docs_text=gate_pairs,
        gate_out=vision_gate,
        prompt_vision=prompt_vision,
        response_schema=response_schema,
        log_label=f"mov_id={mov.mov_id}",
        thinking_budget=0,
        # max_tokens default(~16384)->65535 (2026-06-17): mov de TEXTO GRANDE gerava
        # card > teto default -> JSON truncado no char ~46K ("Unterminated string"/
        # "Expecting ',' delimiter") -> parse_500 -> mov falha -> l1_degraded. Mesma
        # raiz dos gigantes corrigida no L2/L3 (PR #37); faltava o L1. Era a causa
        # dominante dos 9 monit indeterminado + parse_500 no contexto global.
        # 65535 (nao 65536): limite da familia 2.5 no Vertex — 65536 da 400
        # INVALID_ARGUMENT (F0 2.5→3.1, 2026-07-21; GeminiProvider tambem clampa).
        max_tokens=65535,
    )

    raw_response = response.text
    try:
        if not (raw_response or "").strip():
            # Resposta VAZIA do modelo — doc ilegível (texto-lixo/OCR) ou safety-block.
            # Card ruido em vez de erro: o mov foi LIDO (nada extraível), NÃO é gap —
            # evita o ciclo erro→500→5 retries→mov-falha→l1_degraded.
            # ponytail: empty determinístico (texto-lixo) re-tenta ao mesmo vazio.
            logger.warning(
                f"L1_EMPTY_RESPONSE mov_id={mov.mov_id} → card ruido (doc ilegível/sem texto)"
            )
            card_data = _stub_ruido_card(mov, use_v4, response_schema, classe)
        elif use_v4:
            # v4: fatos neutros + derivados sujeito-independentes (G6). Identidade injetada
            # dentro do helper (mov_id/data fora do response_schema). Ramo peticao valida
            # com o superset (a base droparia cdas/processos_citados).
            parsed = parse_llm_json(raw_response)
            card_data = _build_card_v4(
                parsed, mov,
                card_cls=response_schema if classe in ("peticao", "doc_incerto") else None,
                sem_corpo=_sem_corpo(mov, docs_typed),
            )
        else:
            # Echo input identifiers em caso de LLM reset
            parsed = parse_llm_json(raw_response)
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
        # L1_PARSE_FAIL diag (2026-06-21): finish_reason distingue MAX_TOKENS / STOP-
        # truncado-sob-carga / SAFETY; out_tokens confirma o teto; prompt_md5 compara
        # com o repro isolado (mesmo md5 → causa é CARGA, não o prompt). Grepável.
        _meta = response.metadata or {}
        _phash = hashlib.md5((prompt or "").encode("utf-8", "replace")).hexdigest()[:12]
        logger.error(
            "L1_PARSE_FAIL mov_id=%s err=%r finish_reason=%s out_tokens=%s "
            "prompt_len=%d prompt_md5=%s resp_len=%d resp_tail=%r",
            mov.mov_id, e, _meta.get("finish_reason"), response.output_tokens,
            len(prompt or ""), _phash, len(raw_response or ""), (raw_response or "")[-120:],
        )
        card_data = {"error": repr(e), "raw": raw_response, "mov_id": mov.mov_id}

    # Leak guard (2026-06-29): JSON VÁLIDO mas o VALOR de resumo_ato carrega o meta-erro de
    # JSON / inglês do modelo (passa no schema permissivo resumo_ato: str). O resto do card
    # (tipo_doc, categoria, decisao, evento_garantia) parseou OK — só o texto do resumo é
    # lixo. O resto do card (tipo_doc/categoria/decisao) parseou OK — só o texto é lixo.
    # Troca o resumo pelo TEXTO CRU do evento (mov.texto) e mantém o card. NÃO pode ser
    # None (schema resumo_ato: str — vira ValidationError->500->engine retenta 6x ~3min à
    # toa) e NÃO devolver erro (idem). MEDIDO: esses movs degeneram em flash-lite E flash
    # (não é flakiness; escalar não recupera). Raiz dos 31 saneados — v2b-citacoes-deploy.
    if (isinstance(card_data, dict) and not card_data.get("error")
            and _resumo_looks_like_json_meta_leak(card_data.get("resumo_ato"))):
        logger.warning(
            "L1_RESUMO_META_LEAK mov_id=%s resumo_head=%r -> texto cru (card mantido)",
            mov.mov_id, (card_data.get("resumo_ato") or "")[:80],
        )
        card_data["resumo_ato"] = (getattr(mov, "texto", "") or "").strip()[:500] or "(resumo indisponivel)"

    usage = {
        "input_tokens": response.input_tokens or 0,
        "output_tokens": response.output_tokens or 0,
        "total_tokens": (response.input_tokens or 0) + (response.output_tokens or 0),
        "cached_tokens": getattr(response, "cached_tokens", 0) or 0,
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
        # O prompt REALMENTE enviado. Com o steering dos anexos são 2 versões e só o
        # helper sabe qual saiu (o gate decide depois do prompt montado); registrar a
        # outra faria o card mentir sobre o que o modelo leu — nesta lane, discrepância
        # invisível entre payload e registro é o modo de falha da casa.
        "llm_raw_prompt": (
            prompt_vision
            if (prompt_vision and usage["model_variant"] == MODEL_VARIANT_VISION)
            else prompt
        ),
        "prompt_version": prompt_version,
        "usage": usage,
        # Veredito do gate pro caller PERSISTIR (sentinela write-time). Sem ele,
        # "nenhum doc precisava de Vision" e "o gate nem foi consultado" ficam
        # indistinguíveis no banco — que é como o ramo de petição passou meses
        # com vision=0 sem ninguém notar.
        "vision_gate": vision_gate,
    }


async def _classify_chunked(
    processo, mov, variants, fb_typed, model, provider, classe,
    documentos_gate=None,
) -> dict:
    """Map-reduce de peça grande via framework compartilhado: N variantes (chunks) →
    classify em PARALELO (cada uma com _no_chunk=True → 1 call normal) → reduz os cards +
    RE-DERIVA (categoria/status/... consistentes com a base reduzida). Custo somado.
    Orquestração genérica em garantis_shared.llm_chunking; reduce por-layer em chunking.py.

    🚨 `documentos_gate` TEM que atravessar. Ele não atravessava, e o buraco era mudo:
    `documentos_anexados` não carrega `gcs_url` no ramo de petição, então perder o campo
    aqui deixa o gate com lista VAZIA — zero Vision, cascade SUCCESS, card gravado, custo
    normal. Medido: **1.050 de 7.230 pns (14,5%)** com petição acima do CHUNK_SIZE de
    180k caem neste caminho, e há um cron dedicado a eles (`backfill-peticao-giants`).

    🚨 E o VEREDITO tem que atravessar de volta: `map_reduce_classify` é genérico (não
    conhece schema de agent nenhum) e o envelope dele não carrega `vision_gate`, então
    o card chunkado chegava ao materializer SEM veredito — invisível à sentinela, com o
    mesmo silêncio que ela existe pra quebrar. Capturado por CLOSURE, não de `ok[0]`: o
    map-reduce filtra os resultados preservando ordem, então se o chunk 0 falhar o parse
    `ok[0]` é OUTRO chunk — e só a variante 0 recebeu os PDFs."""
    gate_v0: dict = {}

    async def _classify_one(v) -> dict:
        resultado = await classify_mov_factsheet(
            processo, mov, v, fb_typed, model, provider, classe,
            # SÓ na 1ª variante: basta UMA chamada ver o conteúdo inalcançável, e o
            # reduce funde os cards. Passar em todas multiplicaria o custo do Vision
            # pelo nº de chunks sem acrescentar informação. `is variants[0]` é
            # identidade de objeto — determinística mesmo com as variantes em paralelo.
            documentos_gate=(documentos_gate if v is variants[0] else None),
            _no_chunk=True,
        )
        if v is variants[0] and isinstance(resultado.get("vision_gate"), dict):
            gate_v0.update(resultado["vision_gate"])
        return resultado

    reduzido = await map_reduce_classify(
        variants=variants,
        classify_one=_classify_one,
        reduce_cards=_reduce_peca_and_rederive,
        label="chunked",
        on_all_fail={
            "card": {"error": "all chunks failed", "mov_id": mov.mov_id},
            "raw_response": "", "llm_raw_prompt": "", "prompt_version": None, "usage": {},
        },
    )
    if gate_v0:
        reduzido["vision_gate"] = gate_v0
    return reduzido


def _reduce_peca_and_rederive(cards: list[dict]) -> dict:
    """reduce_peca_cards + RE-DERIVA (categoria/status/...) na base reduzida. Passado como
    reduce_cards pro map_reduce_classify — o re-derive entra DENTRO do reduce (o card de
    saída fica byte-idêntico ao do _classify_chunked pré-extração)."""
    from garantis_shared.engine_v6.layer1_mov_factsheet.derivacoes import (
        aplicar_derivados_sujeito_indep,
    )
    reduced = reduce_peca_cards(cards)
    aplicar_derivados_sujeito_indep(reduced)  # re-derive na base reduzida
    return reduced

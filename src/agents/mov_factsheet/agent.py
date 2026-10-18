"""Mov FactSheet Agent — engine v6_meritos camada 1.

Single LLM call por movimentacao, extrai 13 campos estruturados (kind='mov_factsheet').
"""

import hashlib
import json
import logging
from typing import Optional

from garantis_shared.llm_chunking import map_reduce_classify
from garantis_shared.llm_models import model_for

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
from .schemas import (
    DocAnexado,
    DocGate,
    MovInput,
    ProcessoContext,
)

logger = logging.getLogger(__name__)

# O engine manda o model no payload (ENGINE_LAYER1_MODEL, que le o mesmo papel); fallback.
DEFAULT_MODEL = model_for("engine_layer1")
DEFAULT_PROVIDER = "gemini"


# ══════════════════════════════════════════════════════════════════════════════
# TRAVA DE CORPO: sem CORPO e sem DOC ANEXO nao ha decisao — e ponto, sem passar pelo
# olho do LLM.
#
# Ela substitui uma instrucao ESTETICA no prompt ("Snippet generico ... =>
# tem_decisao=false"), que pedia ao modelo um julgamento de gosto sobre a propria
# entrada. Essa instrucao falha por construcao quando o rotulo do catalogo do
# provider CONTEM as palavras do desfecho: "Julgado - Julgado improcedente o
# pedido" (39 chars, sem corpo, sem doc) nao e generico — e especifico e ERRADO,
# e ate o campo `dispositivo` (que exige o trecho literal) e satisfeito por ele,
# porque a frase esta mesmo la.
#
# A trava e MECANICA e usa so o que a funcao ja tem em maos — `mov.texto` e
# `documentos_anexados`. ⛔ NAO precisa do `metadata` do provider: o
# `classificacao_automatica` do jusbrasil e o `step_type` do judit aparecem tanto em
# etiqueta quanto em texto REAL — nenhum dos dois separa etiqueta de documento, e
# nenhum existe em tjsp_legacy/datalake/escavador.
#
# O CORTE em 60 chars e medido, nao escolhido: ate 60 chars quase todo card vem de
# etiqueta de catalogo; na faixa 61-120 o texto real ja e 1 em 4.
# ⛔ Nao suba o teto pra "pegar mais": a 120 a trava silenciaria 1 ato real em 4.
# ⚠️ TETO DECLARADO: sobram cards-etiqueta na faixa 61-120 que esta trava NAO
# alcanca. Pegar aquela faixa exige outro discriminador (voz do juiz / cardinalidade
# da string), nao um numero maior.
#
# ⛔ A trava e incondicional (nao ha flag; decisao do Elton): apagar decisao fabricada
# move banda nos DOIS sentidos, e a trava ligada e o comportamento decidido.
#
# O corte (`CORPO_MIN_CHARS`) mora em `prompts_v4.py` e so `_sem_corpo` o le.


def _sem_corpo(mov: "MovInput", docs: list) -> bool:
    """A unidade nao tem sobre o que decidir. PURA (testavel sem LLM/banco).

    TRES estados, nao dois — "lista de docs vazia" e ambiguo:

      1. ha doc admissivel                 -> False (o agent le o doc)
      2. NAO existe documento nenhum       -> True  (rotulo do provider sem lastro)
      3. existe doc e nao foi admitido     -> False (ponteiro pra peca que nao demos conta
                                                     de ler; apagar perderia fato REAL)

    O 3o caso e raro (ex.: uma sentenca com `has_text=false` E `gcs_url` NULL — a peca
    EXISTE, so nao chega aqui), mas e o unico em que a trava erraria, e na direcao
    perigosa (sub-rating).

    `docs_inadmissiveis` vem carimbado pelo loader do shared
    (`fetch_docs_for_movs_batch`). Ausente/0 = so os estados 1 e 2.
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
# TRAVA DE DISPOSITIVO: sem a ANCORA, o L1 nao afirma decisao.
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
# ⛔ A trava e incondicional (nao ha flag), igual a de corpo. O custo declarado: decisao
# LEGITIMA que o modelo simplesmente nao soube citar cai junto (falso positivo de
# higiene virando perda de sinal).


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
    passa PeticaoExtractCardV4 — superset; validar com a base DROPARIA cdas/citados)."""
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
        # O log conta a decisao que a trava apaga: e o volume do custo declarado na trava.
        logger.warning(
            "L1_DECISAO_SEM_ANCORA mov_id=%s natureza=%s tipo_doc=%s",
            mov.mov_id, (card_data.get("decisao") or {}).get("natureza"),
            card_data.get("tipo_doc"),
        )
        _zerar_decisao(card_data)                # idem — a ancora e a outra metade
    aplicar_derivados_sujeito_indep(card_data)   # G6: categoria/status/relevante/peca_pivo (in-place)
    return card_data


async def classify_mov_factsheet(
    processo: ProcessoContext | dict,
    mov: MovInput | dict,
    documentos_anexados: list[DocAnexado | dict] | None = None,
    model: Optional[str] = None,
    provider: str = DEFAULT_PROVIDER,
    classe: Optional[str] = None,
    documentos_gate: list[DocGate | dict] | None = None,
    _no_chunk: bool = False,
    _resposta: Optional[LLMResponse] = None,
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
        model: override Gemini model
        provider: 'gemini' (default)

    Returns:
        {"card": MovFactSheetCardV4.model_dump() | error_dict,
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
    # de N documentos somado contra o gcs_url de UM (o primário), que pode ser
    # outra peça (um agravo), não a petição. Ver `documentos_gate`.
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

    if model is None:
        model = DEFAULT_MODEL

    llm_provider = create_provider(provider)

    # CHUNK GATE (v4): peça grande (>CHUNK_SIZE) estoura o L1 (Gemini >60s →
    # TIMEOUT_LAYER1_S). Split em chunks, classifica cada um em PARALELO e reduz por
    # campo (lê COMPLETO sem timeout). Evidência já vai head+tail no prompt builder; só
    # peça precisa. Recursa com _no_chunk=True (cada chunk <CHUNK_SIZE → 1 call normal).
    if not _no_chunk:
        variants = split_large_peca_variants(docs_typed)
        if variants:
            return await _classify_chunked(
                processo, mov, variants, model, provider, classe,
                gate_typed,
            )

    # Caminho neutro: prompt + response_schema v4.
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
            classe=classe,
            pdfs_anexados=True,
        )
    if classe == "peticao":
        # Ramo PETICAO (peticao_extract): schema SUPERSET (card v4 +
        # cdas/processos_citados) e versao POR RAMO — bump da peticao nao invalida
        # cache do mov_factsheet e vice-versa. Opt-in do caller: quem manda
        # classe='peticao' (ou 'doc_incerto') e o materializer de peticao do shared.
        prompt_version = PETICAO_PROMPT_VERSION
        response_schema = PeticaoExtractCardV4
    elif classe == "doc_incerto":
        # Ramo 1X (doc_incerto_extract): fallback do identify — doc do 1o dia
        # sem tipo confirmado. MESMO schema superset; a prompt CLASSIFICA o tipo
        # em vez de crava-lo (decisao do Elton).
        prompt_version = DOC_INCERTO_PROMPT_VERSION
        response_schema = PeticaoExtractCardV4

    # Seed determinístico (mov + prompt) — o MESMO padrão de L2/L3
    # (processo_synthesis/merito_synthesis).
    #
    # POR QUE no L1: `temperature=0.0` NÃO é determinismo — o Gemini a temp=0 sem
    # seed tem micro-ruído de decode entre runs, e no L1 esse ruído não sai como
    # "outro fraseado": sai como OUTRO RÓTULO em campo enumerado (o MESMO número
    # administrativo lido como `paf` numa leitura e `pa` na outra, mesmo mov e doc).
    #
    # As `parts` do seed: `mov.mov_id` + o `prompt` inteiro. O `mov_id` é
    # REDUNDANTE POR CONSTRUÇÃO: o `build_mov_factsheet_prompt_v4` já embute o literal
    # do mov_id DENTRO do prompt (trocar o mov_id muda o prompt), então o prompt
    # sozinho já discrimina E já estabiliza. Ele fica por simetria com o padrão de
    # L2/L3, e não perde caso vivo: as leituras discordantes vêm do MESMO mov_id E do
    # MESMO doc_id.
    # ⚠️ A redundância é CONDICIONAL ao prompt seguir embutindo o mov_id — e essa
    # dependência mora em `prompts_v4.py`, não aqui. Se o prompt parar de embuti-lo,
    # esta part deixa de ser decorativa e vira a ÚNICA coisa que separa leituras de
    # mov_ids diferentes. (O mesmo doc lido sob mov_ids diferentes não depende dela:
    # o prompt já difere, e o seed já difere sem ela.)
    #
    # ⛔ `seed` é best-effort no Gemini — trate como "mesma resposta na maior parte
    # das vezes", nunca como garantia.
    seed = seed_for("mov_factsheet", mov.mov_id, prompt)

    # `_resposta`: a resposta de 1 lote do PDF acima do cap, já lida (ver `_classify_lotes`).
    lotes: list = []
    response: LLMResponse = _resposta if _resposta is not None else await call_l1_with_vision_fallback(
        llm_provider,
        model=model,
        prompt=prompt,
        gcs_urls=gate_urls,
        seed=seed,
        # GATE DE OCR (L1 v7): pares (text_content, gcs_url) por doc — o gate decide
        # por documento se manda pro Vision (texto-lixo OU pagina-imagem). Ver ocr_gate.
        docs_text=gate_pairs,
        gate_out=vision_gate,
        # O PDF acima do cap sobe em lotes de páginas, e o redutor da peça grande junta os
        # cards. Só no v4, como o chunking: o redutor lê o card v4.
        lotes_out=lotes if use_v4 else None,
        prompt_vision=prompt_vision,
        response_schema=response_schema,
        log_label=f"mov_id={mov.mov_id}",
        thinking_budget=0,
        # max_tokens 65535: mov de TEXTO GRANDE estoura o teto default (~16384) -> JSON
        # truncado ("Unterminated string"/"Expecting ',' delimiter") -> parse_500 -> mov
        # falha -> l1_degraded (a mesma raiz dos gigantes no L2/L3).
        # 65535 (nao 65536): 65536 da 400 INVALID_ARGUMENT no Vertex (o GeminiProvider
        # tambem clampa).
        max_tokens=65535,
    )
    if len(lotes) > 1:
        return await _classify_lotes(
            processo, mov, docs_typed, fb_typed, model, provider, classe, lotes, vision_gate,
        )

    raw_response = response.text
    # Resposta VAZIA vira erro no parse, como o JSON quebrado: card sem leitura afirmaria
    # relevancia. O L1_PARSE_FAIL leva o finish_reason, e o mov entra no l1_degraded.
    try:
        # v4: fatos neutros + derivados sujeito-independentes (G6). Identidade injetada
        # dentro do helper (mov_id/data fora do response_schema). Ramo peticao valida
        # com o superset (a base droparia cdas/processos_citados).
        parsed = parse_llm_json(raw_response)
        card_data = _build_card_v4(
            parsed, mov,
            card_cls=response_schema if classe in ("peticao", "doc_incerto") else None,
            sem_corpo=_sem_corpo(mov, docs_typed),
        )
    except (json.JSONDecodeError, Exception) as e:
        # L1_PARSE_FAIL diag: finish_reason distingue MAX_TOKENS / STOP-
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
        # indistinguíveis no banco.
        "vision_gate": vision_gate,
    }


async def _classify_chunked(
    processo, mov, variants, model, provider, classe,
    documentos_gate=None,
) -> dict:
    """Map-reduce de peça grande via framework compartilhado: N variantes (chunks) →
    classify em PARALELO (cada uma com _no_chunk=True → 1 call normal) → reduz os cards +
    RE-DERIVA (categoria/status/... consistentes com a base reduzida). Custo somado.
    Orquestração genérica em garantis_shared.llm_chunking; reduce por-layer em chunking.py.

    🚨 `documentos_gate` TEM que atravessar, e o buraco é mudo: `documentos_anexados`
    não carrega `gcs_url` no ramo de petição, então perder o campo aqui deixa o gate com
    lista VAZIA — zero Vision, cascade SUCCESS, card gravado, custo normal. Toda petição
    acima do CHUNK_SIZE cai neste caminho, e há um cron dedicado a elas
    (`backfill-peticao-giants`).

    🚨 E o VEREDITO tem que atravessar de volta: `map_reduce_classify` é genérico (não
    conhece schema de agent nenhum) e o envelope dele não carrega `vision_gate`, então
    sem isto o card chunkado chega ao materializer SEM veredito — invisível à sentinela,
    com o mesmo silêncio que ela existe pra quebrar. Capturado por CLOSURE, não de `ok[0]`: o
    map-reduce filtra os resultados preservando ordem, então se o chunk 0 falhar o parse
    `ok[0]` é OUTRO chunk — e só a variante 0 recebeu os PDFs."""
    gate_v0: dict = {}

    async def _classify_one(v) -> dict:
        resultado = await classify_mov_factsheet(
            processo, mov, v, model, provider, classe,
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


async def _classify_lotes(
    processo, mov, docs, fb_typed, model, provider, classe, lotes, vision_gate,
) -> dict:
    """O PDF acima do cap, lido em lotes de páginas: o helper devolve 1 resposta por lote.
    Cada resposta vira card pelo caminho de sempre (`_resposta`, sem nova chamada), e o card
    final sai do MESMO redutor por campo da peça grande em texto (`_reduce_peca_and_rederive`).
    Custo somado. O lote cujo card não parseou também ficou fora do card, e entra em
    `n_lotes_falha` junto com o que o helper contou."""
    async def _um_lote(resposta) -> dict:
        return await classify_mov_factsheet(
            processo, mov, documentos_anexados=docs, fallback_context=fb_typed, model=model,
            provider=provider, classe=classe, _no_chunk=True, _resposta=resposta,
        )

    reduzido = await map_reduce_classify(
        variants=lotes,
        classify_one=_um_lote,
        reduce_cards=_reduce_peca_and_rederive,
        label="lotes",
        on_all_fail={
            "card": {"error": "all lotes failed", "mov_id": mov.mov_id},
            "raw_response": "", "llm_raw_prompt": "", "prompt_version": None, "usage": {},
        },
    )
    falhas = len(lotes) - reduzido.get("n_ok", 0)
    vision_gate["n_lotes_falha"] += falhas
    if falhas:
        # O PDF lido em parte não conta como enviado, como na falha HTTP do helper, e a
        # régua do CEGO o vê. Desconta 1 por lote: 2 lotes do mesmo PDF passam do número
        # exato, mas o PDF lido em parte já deixa a leitura incompleta.
        vision_gate["n_enviados"] = max(0, vision_gate.get("n_enviados", 0) - falhas)
    reduzido["vision_gate"] = vision_gate
    return reduzido


def _reduce_peca_and_rederive(cards: list[dict]) -> dict:
    """reduce_peca_cards + RE-DERIVA (categoria/status/...) na base reduzida. Passado como
    reduce_cards pro map_reduce_classify — o re-derive entra DENTRO do reduce."""
    from garantis_shared.engine_v6.layer1_mov_factsheet.derivacoes import (
        aplicar_derivados_sujeito_indep,
    )
    reduced = reduce_peca_cards(cards)
    aplicar_derivados_sujeito_indep(reduced)  # re-derive na base reduzida
    return reduced

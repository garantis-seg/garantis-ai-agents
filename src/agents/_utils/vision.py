"""Helper Vision L1 — chamadas multimodais (PDF→Gemini Vision) do
mov_factsheet (day_factsheet usava tambem, ate o teardown 2026-06-13).

Acionado quando flag VISION_L1_ENABLED=true E o caller fornece pelo menos 1
gcs_url no input. Roteamento inline vs Files API decidido per-call por
tamanho de payload:

  - Total ≤15MB E maior PDF ≤5MB → inline (`types.Blob` direto, latência baixa)
  - Senão → Files API (`client.aio.files.upload` + `Part.from_uri`,
    suporta até 2GB per file, ~200-500ms overhead por upload)

Sem essa lógica, PDFs grandes seriam dropados silenciosamente (Gemini inline
blob limit ~20MB total por request). Files API absorve qualquer tamanho até
o sanity cap (100MB per PDF).
"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from typing import Any, Literal, Optional

logger = logging.getLogger(__name__)

ModelVariant = Literal["text", "vision"]
MODEL_VARIANT_TEXT: ModelVariant = "text"
MODEL_VARIANT_VISION: ModelVariant = "vision"

# Limite concurrent GCS reads — evita exhaustion de connection pool em cascades
# com 100+ docs (1 fetch por doc).
_GCS_FETCH_SEMAPHORE_LIMIT = 5

# Cap de PDFs por chamada Gemini Vision — evita estouro de context window.
_MAX_PDFS_PER_CALL = 20

# Decisão inline vs Files API:
#   inline → faster (~0 overhead), bom pra caso comum.
#   Files API → suporta PDFs grandes, ~200-500ms overhead por upload.
# Caps inline conservadores deixam margem pro buffer da request envelope.
_INLINE_TOTAL_BYTES_CAP = 15 * 1024 * 1024   # 15MB
_INLINE_PER_PDF_BYTES_CAP = 5 * 1024 * 1024  # 5MB

# Sanity guard absoluto. PDF >100MB sinaliza bug upstream (GCS read errado).
# Dropa esse PDF específico mas NÃO bloqueia a Vision call dos restantes.
_MAX_PDF_BYTES = 100 * 1024 * 1024

# Concurrent uploads pra Files API (rate-limit defensivo).
_FILES_API_UPLOAD_SEMAPHORE_LIMIT = 3

_storage_client: Any = None


def _get_storage_client() -> Optional[Any]:
    """Singleton `google.cloud.storage.Client()`. None se lib não instalada."""
    global _storage_client
    if _storage_client is not None:
        return _storage_client
    try:
        from google.cloud import storage  # type: ignore
    except ImportError:
        logger.warning("[VisionL1] google-cloud-storage não instalado — pulando Vision path")
        return None
    _storage_client = storage.Client()
    return _storage_client


def _parse_gcs_url(gcs_url: str) -> tuple[str, str]:
    """gs://bucket/path -> (bucket, path). Raises ValueError pra URLs inválidos."""
    if not gcs_url.startswith("gs://"):
        raise ValueError(f"not a gs:// URL: {gcs_url}")
    body = gcs_url[5:]
    bucket, _, path = body.partition("/")
    if not bucket or not path:
        raise ValueError(f"malformed gs:// URL: {gcs_url}")
    return bucket, path


async def _fetch_pdf_bytes(storage_client, gcs_url: str) -> Optional[bytes]:
    """Baixa 1 PDF do GCS. None em qualquer erro (swallow + log)."""
    try:
        bucket_name, blob_path = _parse_gcs_url(gcs_url)
        blob = storage_client.bucket(bucket_name).blob(blob_path)
        return await asyncio.to_thread(blob.download_as_bytes)
    except Exception as exc:
        logger.warning(f"[VisionL1] GCS fetch failed for {gcs_url}: {exc}")
        return None


# Stub "acesso restrito" da jusbrasil — byte-idêntico, ~46% dos PDFs baixados num
# proc trabalhista real (498/1076). LibreOffice 1-pág "Documento não existe ou possui
# acesso restrito". Vision só devolveria "ilegível", então dropamos ANTES da call →
# cai no fallback text-only (mais barato) em vez de gastar tokens de PDF.
# (PDF 0-página/corrompido NÃO entra aqui: é raro e o guard de
# call_l1_with_vision_fallback já o pega via o Gemini 400 → fallback text. Mantém
# este filtro stdlib-only e trivial de testar.)
# ponytail: hash-set de stubs conhecidos; cresce se a jusbrasil trocar o placeholder
# (sniff pelo texto "acesso restrito" seria o upgrade se virar zoo de variantes).
_KNOWN_UNREADABLE_PDF_SHA256 = {
    "cd7214ba72437d624548b9493174f7d51080670cc4eee2269db8f1a06b75f712",
}


def _pdf_is_unreadable(pdf_bytes: bytes) -> bool:
    """True se o PDF é um stub conhecido de 'acesso restrito' (byte-idêntico)."""
    import hashlib

    return hashlib.sha256(pdf_bytes).hexdigest() in _KNOWN_UNREADABLE_PDF_SHA256


async def fetch_pdfs_from_gcs(gcs_urls: list[str]) -> list[bytes]:
    """Baixa N PDFs do GCS em paralelo. Aplica sanity cap por PDF (100MB —
    defende contra bug de GCS read absurdo) e dropa PDFs ilegíveis/stub
    (`_pdf_is_unreadable`). Resto vai pra `call_vision_l1` que decide inline
    vs Files API.
    """
    if not gcs_urls:
        return []

    storage_client = _get_storage_client()
    if storage_client is None:
        return []

    semaphore = asyncio.Semaphore(_GCS_FETCH_SEMAPHORE_LIMIT)

    async def _bounded(url: str) -> Optional[bytes]:
        async with semaphore:
            return await _fetch_pdf_bytes(storage_client, url)

    capped = gcs_urls[:_MAX_PDFS_PER_CALL]
    if len(gcs_urls) > _MAX_PDFS_PER_CALL:
        logger.info(
            f"[VisionL1] {len(gcs_urls)} PDFs solicitados, cap={_MAX_PDFS_PER_CALL} "
            "aplicado pra evitar context overflow"
        )
    results = await asyncio.gather(*[_bounded(u) for u in capped])

    accepted: list[bytes] = []
    for b in results:
        if not b:
            continue
        if len(b) > _MAX_PDF_BYTES:
            logger.warning(
                f"[VisionL1] PDF {len(b)}B > {_MAX_PDF_BYTES}B sanity cap — dropado"
            )
            continue
        if _pdf_is_unreadable(b):
            logger.info(
                f"[VisionL1] PDF ilegível/stub ({len(b)}B) — dropado (skip Vision)"
            )
            continue
        accepted.append(b)

    return accepted


async def _upload_pdf_to_gemini(client, types, pdf_bytes: bytes) -> Any:
    """Upload PDF via Files API. SDK requer path-like — usa tempfile + cleanup."""
    fd, path = tempfile.mkstemp(suffix=".pdf")
    try:
        os.write(fd, pdf_bytes)
        os.close(fd)
        return await client.aio.files.upload(
            file=path,
            config=types.UploadFileConfig(mime_type="application/pdf"),
        )
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


async def _build_pdf_parts(
    client, types, pdf_bytes_list: list[bytes],
) -> tuple[list[Any], str]:
    """Constrói parts pra contents do Gemini. Retorna (parts, transport).

    transport ∈ {'inline', 'files_api'} — usado pra logging/telemetria.
    """
    total_bytes = sum(len(b) for b in pdf_bytes_list)
    largest = max(len(b) for b in pdf_bytes_list)

    use_inline = (
        total_bytes <= _INLINE_TOTAL_BYTES_CAP
        and largest <= _INLINE_PER_PDF_BYTES_CAP
    )

    if use_inline:
        parts = [
            types.Part(inline_data=types.Blob(mime_type="application/pdf", data=b))
            for b in pdf_bytes_list
        ]
        return parts, "inline"

    upload_sem = asyncio.Semaphore(_FILES_API_UPLOAD_SEMAPHORE_LIMIT)

    async def _upload_one(b: bytes) -> Any:
        async with upload_sem:
            return await _upload_pdf_to_gemini(client, types, b)

    uploaded = await asyncio.gather(*[_upload_one(b) for b in pdf_bytes_list])
    parts = [
        types.Part.from_uri(file_uri=f.uri, mime_type="application/pdf")
        for f in uploaded
    ]
    return parts, "files_api"


async def call_vision_l1(
    provider,
    *,
    model: str,
    prompt: str,
    pdf_bytes_list: list[bytes],
    response_schema=None,
    temperature: float = 0.0,
    thinking_budget: int = 0,
    max_tokens: int | None = None,
) -> Any:
    """Chama Gemini Vision com PDFs + prompt text. Retorna LLMResponse.

    Roteia inline vs Files API automaticamente por tamanho (ver
    `_build_pdf_parts`). Caller é responsável por garantir `pdf_bytes_list`
    não-vazio.
    """
    if not pdf_bytes_list:
        raise ValueError("call_vision_l1 requires at least 1 PDF")

    client = provider._client
    types = provider._types

    pdf_parts, transport = await _build_pdf_parts(client, types, pdf_bytes_list)
    parts = pdf_parts + [types.Part.from_text(text=prompt)]

    config_kwargs: dict[str, Any] = {"temperature": temperature}
    if response_schema is not None:
        config_kwargs["response_mime_type"] = "application/json"
        config_kwargs["response_schema"] = response_schema
    if max_tokens:
        config_kwargs["max_output_tokens"] = max_tokens
    if thinking_budget == 0:
        try:
            config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
        except Exception:
            pass

    config = types.GenerateContentConfig(**config_kwargs)

    logger.info(
        f"[VisionL1] Calling Gemini Vision via {transport}: {len(pdf_bytes_list)} PDFs, "
        f"sum={sum(len(b) for b in pdf_bytes_list)} bytes, model={model}"
    )

    response = await client.aio.models.generate_content(
        model=model,
        contents=parts,
        config=config,
    )

    from ...providers.base import LLMResponse

    input_tokens = 0
    output_tokens = 0
    if hasattr(response, "usage_metadata") and response.usage_metadata:
        input_tokens = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
        output_tokens = getattr(response.usage_metadata, "candidates_token_count", 0) or 0

    pricing = provider.get_model_pricing(model)
    cost = (
        (input_tokens / 1_000_000) * pricing.get("input_per_1m", 0)
        + (output_tokens / 1_000_000) * pricing.get("output_per_1m", 0)
    )

    return LLMResponse(
        text=response.text or "",
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        # Vision NAO le cached_content_token_count (a formula de custo local acima e
        # flat); 0 explicito pra deixar claro que e nao-instrumentado, nao ausencia
        # de cache. Mudar isso mexeria no cost_usd de model_variant='vision'.
        cached_tokens=0,
        metadata={
            "cost_usd": round(cost, 6),
            "model_variant": MODEL_VARIANT_VISION,
            "pdfs_processed": len(pdf_bytes_list),
            "vision_transport": transport,
        },
    )


async def call_l1_with_vision_fallback(
    provider,
    *,
    model: str,
    prompt: str,
    gcs_urls: list[str],
    response_schema,
    vision_flag_name: str = "VISION_L1_ENABLED",
    log_label: str = "",
    thinking_budget: int = 0,
    docs_text: Optional[list[tuple[Optional[str], Optional[str]]]] = None,
    max_tokens: int | None = None,
    gate_out: Optional[dict] = None,
    prompt_vision: Optional[str] = None,
) -> Any:
    """High-level helper pros agents L1 (mov/day).

    Roteia entre Vision e Text:
    - `vision_flag_name` ON + ≥1 gcs_url + ≥1 PDF fetchável → Vision path
    - else → `provider.agenerate(prompt, model, ...)` text-only fallback

    Caller monta o prompt — esse helper só roteia + fetcha PDFs. Single
    source da Vision branch (elimina copy-paste em cada agent L1).

    GATE DE OCR (L1 v7): se `docs_text` (lista de (text_content, gcs_url)) for
    passado, aplica o gate por documento (ocr_gate.precisa_vision) — só os docs com
    texto-lixo OU página-imagem vão pro Vision; os demais ficam no texto do prompt.
    Sem `docs_text` (callers legados como day), mantém o comportamento atual (todos
    os gcs_urls fetchados vão pro Vision). Fallback seguro em qualquer falha do gate.

    `log_label` é appended em warnings de fallback (ex: "mov_id=X").

    `gate_out` (dict mutável, opcional) recebe o VEREDITO do gate pro caller
    persistir: {n_docs, n_inalcancaveis, n_enviados, motivo}. É a metade write-time
    da sentinela — sem ela, "o gate não mandou nada" e "o gate nem rodou" produzem
    exatamente o mesmo silêncio no banco. `n_enviados` conta o que o Gemini
    REALMENTE recebeu: se a Vision call falhar e cair no texto, ele volta a 0 (o
    card é cego, e é isso que a métrica tem que dizer).

    `prompt_vision` (opcional) é o prompt alternativo pro ramo VISION — o caller o
    monta sabendo que PODE haver anexo, e este helper decide se ele vale. Existe
    porque o gate só sabe se há PDF DEPOIS de baixar e julgar, e o prompt é montado
    ANTES: sem isto, ou o steering dos anexos entraria em toda chamada (mentindo no
    caminho texto, 99,7% do volume) ou o helper teria que remontar prompt, o que é
    conhecimento do agent. Ausente ⇒ `prompt` nos dois ramos, como sempre.
    ⚠️ O fallback text-only usa SEMPRE `prompt`: se a Vision call falhar, não há
    anexo nenhum na chamada e o steering viraria instrução sobre PDF inexistente.
    """
    from .feature_flags import flag_enabled

    if gate_out is not None:
        gate_out.update({"n_docs": 0, "n_inalcancaveis": 0, "n_enviados": 0,
                         "motivo": None})
    pdf_bytes_list: list[bytes] = []
    motivos: list[str] = []
    if gcs_urls and flag_enabled(vision_flag_name):
        if docs_text:
            # GATE por documento: baixa e filtra só os que o gate aprova.
            from .ocr_gate import precisa_vision, texto_decide_sozinho
            for text_content, gcs_url in docs_text:
                if not gcs_url:
                    continue
                if gate_out is not None:
                    gate_out["n_docs"] += 1
                if len(pdf_bytes_list) >= _MAX_PDFS_PER_CALL:
                    # O cap de `fetch_pdfs_from_gcs` NÃO alcança este ramo: aqui o
                    # fetch é 1 URL por vez, então a lista cresceria sem teto (o
                    # conjunto multi-doc da petição vai até 25). Corta aqui.
                    # WARNING, não info: no ramo de petição os documentos chegam
                    # com a PETIÇÃO NA FRENTE (o materializer ordena assim de
                    # propósito), então bater este cap significa que sobrou parte de
                    # peça sem ser lida — e corte silencioso do documento mais
                    # importante do produto é o pior modo de falha aqui.
                    logger.warning(
                        f"[VisionL1] {log_label}: cap={_MAX_PDFS_PER_CALL} PDFs atingido"
                        f" no gate per-doc ({len(docs_text)} docs no conjunto); os"
                        " restantes ficam no texto",
                    )
                    break
                # route-by-has_text (núcleo OCR per-doc 2026-06-13): doc com texto
                # USÁVEL fica no texto do prompt SEM baixar o PDF — o ingest já extraiu
                # o text-layer (born-digital). Só doc-imagem/texto-lixo (vazio ou
                # garbage) baixa + passa pelo gate. Assim o custo do Vision ON é ∝ nº de
                # docs-imagem (~5%), não ao total de docs (antes baixava TODOS pra gate).
                # ⚠️ O teste era `not texto_lixo(...)`, e isso deixava o Sinal 1 (área de
                # imagem) INALCANÇÁVEL justamente pro caso que ele foi escrito pra pegar:
                # scan cujo único texto é o carimbo do PJe / rodapé do ESAJ — limpo pro
                # rmgarbage, e com a peça presa na imagem. 8.597 docs assim em prod
                # (2026-08-10). `texto_decide_sozinho` soma o piso de TEOR.
                if texto_decide_sozinho(text_content):
                    continue
                try:
                    raw = await fetch_pdfs_from_gcs([gcs_url])
                    pdf_bytes = raw[0] if raw else None
                except Exception:
                    pdf_bytes = None
                manda, info = precisa_vision(text_content, pdf_bytes)
                if manda:
                    pdf_bytes_list.append(info.get("_pdf_bytes") or pdf_bytes)
                    if gate_out is not None:
                        gate_out["n_inalcancaveis"] += 1
                    motivos.extend((info.get("_nota") or {}).get("motivos") or {})
        else:
            pdf_bytes_list = await fetch_pdfs_from_gcs(gcs_urls)

    if gate_out is not None and motivos:
        gate_out["motivo"] = ",".join(sorted(set(motivos)))

    if pdf_bytes_list:
        try:
            resposta = await call_vision_l1(
                provider,
                model=model,
                prompt=prompt_vision or prompt,
                pdf_bytes_list=pdf_bytes_list,
                response_schema=response_schema,
                temperature=0.0,
                thinking_budget=thinking_budget,
                max_tokens=max_tokens,
            )
            if gate_out is not None:
                gate_out["n_enviados"] = len(pdf_bytes_list)
            return resposta
        except Exception as exc:
            # Guard: Gemini 400 (ex: "document has no pages" em PDF corrompido) ou
            # qualquer falha da Vision call NÃO pode derrubar a cascade — cai no
            # text-only abaixo. ponytail: fallback existente cobre; sem reraise.
            logger.warning(
                f"[VisionL1] {log_label}: Vision call falhou ({exc!r}); fallback pra text-only",
            )
    elif gcs_urls and flag_enabled(vision_flag_name):
        logger.warning(
            f"[VisionL1] {log_label}: flag ON mas 0 PDFs fetchados; fallback pra text-only",
        )

    return await provider.agenerate(
        prompt=prompt,
        model=model,
        temperature=0.0,
        response_schema=response_schema,
        thinking_budget=thinking_budget,
        max_tokens=max_tokens,
    )

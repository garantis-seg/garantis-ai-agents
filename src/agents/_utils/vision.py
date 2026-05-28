"""Helper Vision L1 — chamadas multimodais (PDF→Gemini Vision) compartilhadas
entre mov_factsheet, day_factsheet e monolith_factsheet.

Acionado quando flag VISION_L1_ENABLED=true E o caller fornece pelo menos 1
gcs_url no input. Caller passa pelo `call_l1_with_vision_fallback` (helper
high-level) ou pelas funções low-level (`fetch_pdfs_from_gcs` +
`call_vision_l1`) quando precisa de controle.
"""
from __future__ import annotations

import asyncio
import logging
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

# Gemini inline blob limit: ~20MB total por request (somando os PDFs).
# Acima disso a API rejeita "request entity too large". Cap defensivo em 18MB
# pra margem. PDFs grandes individualmente são droppados (não dá pra splittar
# sem perder semântica multi-página).
_GEMINI_INLINE_TOTAL_BYTES_CAP = 18 * 1024 * 1024
_GEMINI_INLINE_PER_PDF_BYTES_CAP = 18 * 1024 * 1024

# Lazy singleton — storage.Client() faz credential discovery + HTTPS pool setup
# (~50-200ms em cold path). Reusar entre chamadas economiza 1-4s por cascade
# com 19 day calls.
_storage_client: Any = None


def _get_storage_client() -> Optional[Any]:
    """Retorna singleton `google.cloud.storage.Client()`. None se lib não
    instalada (ambiente legado pré-Vision-flag)."""
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


async def fetch_pdfs_from_gcs(gcs_urls: list[str]) -> list[bytes]:
    """Baixa N PDFs do GCS em paralelo (cap=Semaphore). Filtra:
    - falhas de fetch (None)
    - PDFs >18MB individuais (excedem limite inline do Gemini)
    - bytes adicionais que ultrapassem _GEMINI_INLINE_TOTAL_BYTES_CAP cumulativo
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
    total_bytes = 0
    for b in results:
        if not b:
            continue
        if len(b) > _GEMINI_INLINE_PER_PDF_BYTES_CAP:
            logger.warning(
                f"[VisionL1] PDF {len(b)} bytes > {_GEMINI_INLINE_PER_PDF_BYTES_CAP} "
                "cap individual — dropado (use Files API se precisar)"
            )
            continue
        if total_bytes + len(b) > _GEMINI_INLINE_TOTAL_BYTES_CAP:
            logger.warning(
                f"[VisionL1] cumulative {total_bytes + len(b)} > "
                f"{_GEMINI_INLINE_TOTAL_BYTES_CAP} cap total — parando antes "
                f"de adicionar mais ({len(accepted)} já aceitos)"
            )
            break
        accepted.append(b)
        total_bytes += len(b)

    return accepted


async def call_vision_l1(
    provider,
    *,
    model: str,
    prompt: str,
    pdf_bytes_list: list[bytes],
    response_schema=None,
    temperature: float = 0.0,
    thinking_budget: int = 0,
) -> Any:
    """Chama Gemini Vision com PDFs inline + prompt text. Retorna LLMResponse.

    Caller é responsável por garantir `pdf_bytes_list` não-vazio (use
    `fetch_pdfs_from_gcs` antes pra obter a lista com cap byte budget aplicado).
    """
    if not pdf_bytes_list:
        raise ValueError("call_vision_l1 requires at least 1 PDF")

    # Provider expõe os tipos Gemini privados; mesmo pattern de pdf_ocr/agent.py.
    # Bound to GeminiProvider (call_vision_l1 só faz sentido pra Gemini hoje).
    client = provider._client
    types = provider._types

    parts = [
        types.Part(inline_data=types.Blob(mime_type="application/pdf", data=b))
        for b in pdf_bytes_list
    ]
    parts.append(types.Part.from_text(text=prompt))

    config_kwargs: dict[str, Any] = {"temperature": temperature}
    if response_schema is not None:
        config_kwargs["response_mime_type"] = "application/json"
        config_kwargs["response_schema"] = response_schema
    if thinking_budget == 0:
        try:
            config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
        except Exception:
            pass

    config = types.GenerateContentConfig(**config_kwargs)

    logger.info(
        f"[VisionL1] Calling Gemini Vision: {len(pdf_bytes_list)} PDFs, "
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
        metadata={
            "cost_usd": round(cost, 6),
            "model_variant": MODEL_VARIANT_VISION,
            "pdfs_processed": len(pdf_bytes_list),
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
) -> Any:
    """High-level helper pros 3 agents L1 (mov/day/monolith).

    Roteia entre Vision e Text:
    - `vision_flag_name` ON + ≥1 gcs_url + ≥1 PDF fetchável → Vision path
    - else → `provider.agenerate(prompt, model, ...)` text-only fallback

    Caller continua responsável por montar o prompt — esse helper só roteia +
    fetcha PDFs + aplica cap de byte budget. Single source da Vision branch
    (eliminaria copy-paste de ~30 LoC em cada agent L1).

    `log_label` é appended em warnings de fallback (ex: "mov_id=X" / "proc=Y date=Z").
    """
    from .feature_flags import flag_enabled

    pdf_bytes_list: list[bytes] = []
    if gcs_urls and flag_enabled(vision_flag_name):
        pdf_bytes_list = await fetch_pdfs_from_gcs(gcs_urls)

    if pdf_bytes_list:
        return await call_vision_l1(
            provider,
            model=model,
            prompt=prompt,
            pdf_bytes_list=pdf_bytes_list,
            response_schema=response_schema,
            temperature=0.0,
            thinking_budget=thinking_budget,
        )

    if gcs_urls and flag_enabled(vision_flag_name):
        logger.warning(
            f"[VisionL1] {log_label}: flag ON mas 0 PDFs fetchados; fallback pra text-only",
        )

    return await provider.agenerate(
        prompt=prompt,
        model=model,
        temperature=0.0,
        response_schema=response_schema,
        thinking_budget=thinking_budget,
    )

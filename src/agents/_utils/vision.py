"""Helper Vision L1 — chamadas multimodais (PDF→Gemini Vision) compartilhadas
entre mov_factsheet, day_factsheet e monolith_factsheet.

Pattern espelha `agents/pdf_ocr/agent.py` (PdfOcrResult flow) mas retorna
LLMResponse compatível com o caminho text-only pra os 3 agents L1 reusarem
sem mudança upstream.

Acionado quando flag VISION_L1_ENABLED=true E o caller fornece pelo menos 1
gcs_url no input (DocAnexado.gcs_url / DayDocInput.gcs_url /
MonolithFactsheetRequest.gcs_url).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Limite concurrent GCS reads — evita exhaustion de connection pool em cascades
# com 100+ docs (1 fetch por doc). Pattern Sprint 4.6.
_GCS_FETCH_SEMAPHORE_LIMIT = 5

# Cap de PDFs por chamada Gemini Vision — evita estouro de context window.
# Gemini 2.5 flash-lite suporta até 1M tokens; 20 PDFs ~= margem segura.
_MAX_PDFS_PER_CALL = 20


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
        # GCS SDK é sync — async via thread pra não bloquear event loop.
        return await asyncio.to_thread(blob.download_as_bytes)
    except Exception as exc:
        logger.warning(f"[VisionL1] GCS fetch failed for {gcs_url}: {exc}")
        return None


async def fetch_pdfs_from_gcs(gcs_urls: list[str]) -> list[bytes]:
    """Baixa N PDFs do GCS em paralelo (cap=Semaphore). Filtra falhas.

    Returns lista de bytes (sem None). Empty list se nenhum sucedeu.
    """
    if not gcs_urls:
        return []

    try:
        from google.cloud import storage  # type: ignore
    except ImportError:
        logger.warning("[VisionL1] google-cloud-storage não instalado — pulando Vision path")
        return []

    storage_client = storage.Client()
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
    return [b for b in results if b]


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

    Reuso direto do pattern em `pdf_ocr/agent.py:54-95`.
    Caller é responsável por garantir `pdf_bytes_list` não-vazio.
    """
    if not pdf_bytes_list:
        raise ValueError("call_vision_l1 requires at least 1 PDF")

    # Access Gemini types nativos via provider (não passa pelo agenerate text path)
    client = provider._client
    types = provider._types

    # Build multimodal content: N PDFs + text prompt no fim (recency anchor)
    parts = [
        types.Part(inline_data=types.Blob(mime_type="application/pdf", data=b))
        for b in pdf_bytes_list
    ]
    parts.append(types.Part.from_text(text=prompt))

    config_kwargs: dict[str, Any] = {"temperature": temperature}
    if response_schema is not None:
        config_kwargs["response_mime_type"] = "application/json"
        config_kwargs["response_schema"] = response_schema

    # Determinismo Bug 4 handoff: greedy strict + thinking OFF em gemini-2.5-*.
    # provider.agenerate() seta isso automaticamente; aqui aplicamos manual.
    if thinking_budget == 0:
        try:
            config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
        except Exception:
            # ThinkingConfig só disponível em flash-thinking / 2.5-*; ignora silently
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

    # Wrap em LLMResponse-shape pra agents reusarem mesma parse logic
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
            "model_variant": "vision",
            "pdfs_processed": len(pdf_bytes_list),
        },
    )

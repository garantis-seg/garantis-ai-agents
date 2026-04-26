"""
Edital Summarizer Agent.

Generates comprehensive structured summaries of government bidding documents (editais)
using LLM providers. Supports two strategies:
- Direct: single LLM call for smaller documents (<80K chars)
- Map-Reduce: chunk documents, summarize each chunk, then merge (>=80K chars)
"""

import asyncio
import json
import logging
import os
import re
from typing import List, Optional, Union

from ...providers import create_provider
from ...providers.base import LLMResponse
from .prompts import (
    SYSTEM_PROMPT,
    MAP_SYSTEM_PROMPT,
    REDUCE_SYSTEM_PROMPT,
    build_user_prompt,
    build_map_prompt,
    build_reduce_prompt,
    format_items,
)
from .schemas import (
    ChunkSummary,
    EditalMetadata,
    EditalSummaryLLMResponse,
    SummarizationRequest,
    SummarizationResponse,
)

logger = logging.getLogger(__name__)

DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER", "gemini")
DEFAULT_SUMMARIZATION_MODEL = os.getenv("DEFAULT_SUMMARIZATION_MODEL", "gemini-2.5-flash-lite")

# Threshold: above this, use map-reduce instead of direct
MAP_REDUCE_THRESHOLD = 80_000
CHUNK_SIZE = 50_000
MAX_RETRIES = 2


def _escape_control_chars_in_strings(text: str) -> str:
    """
    Walk through JSON text character by character and escape control characters
    (newlines, tabs, etc.) that appear inside string values.

    This handles the most common Gemini bug: literal newlines inside JSON strings
    which cause "Unterminated string" errors.
    """
    result = []
    in_string = False
    i = 0
    length = len(text)

    while i < length:
        ch = text[i]

        if in_string:
            if ch == '\\' and i + 1 < length:
                # Already escaped sequence — keep as-is
                result.append(ch)
                result.append(text[i + 1])
                i += 2
                continue
            elif ch == '"':
                # End of string
                in_string = False
                result.append(ch)
            elif ch == '\n':
                result.append('\\n')
            elif ch == '\r':
                result.append('\\r')
            elif ch == '\t':
                result.append('\\t')
            elif ord(ch) < 0x20:
                # Other control characters
                result.append(f'\\u{ord(ch):04x}')
            else:
                result.append(ch)
        else:
            if ch == '"':
                in_string = True
            result.append(ch)

        i += 1

    return ''.join(result)


def _close_truncated_json(text: str) -> str:
    """
    Attempt to close truncated JSON by balancing braces/brackets.

    When Gemini hits max_output_tokens, JSON is cut mid-string or mid-object.
    This detects the truncation and closes the structure so json.loads() can parse it.
    """
    # If it already ends with } and parses, no fix needed
    stripped = text.rstrip()
    if stripped.endswith("}"):
        return text

    # Find if we're inside a string (odd number of unescaped quotes)
    in_string = False
    i = 0
    while i < len(stripped):
        ch = stripped[i]
        if ch == '\\' and in_string:
            i += 2  # skip escaped char
            continue
        if ch == '"':
            in_string = not in_string
        i += 1

    # If truncated inside a string, close the string first
    if in_string:
        stripped += '"'

    # Remove any trailing comma or colon (incomplete key-value)
    stripped = re.sub(r'[,:\s]+$', '', stripped)

    # Count unclosed braces/brackets and close them
    open_braces = 0
    open_brackets = 0
    in_str = False
    j = 0
    while j < len(stripped):
        ch = stripped[j]
        if ch == '\\' and in_str:
            j += 2
            continue
        if ch == '"':
            in_str = not in_str
        elif not in_str:
            if ch == '{':
                open_braces += 1
            elif ch == '}':
                open_braces -= 1
            elif ch == '[':
                open_brackets += 1
            elif ch == ']':
                open_brackets -= 1
        j += 1

    # Close in reverse order (brackets first, then braces)
    stripped += ']' * max(0, open_brackets)
    stripped += '}' * max(0, open_braces)

    return stripped


def _repair_json(text: str) -> str:
    """Attempt to repair common JSON issues from LLM output."""
    # Step 1: Escape control characters inside string values
    text = _escape_control_chars_in_strings(text)

    # Step 2: Remove trailing commas: ,} or ,]
    text = re.sub(r",\s*}", "}", text)
    text = re.sub(r",\s*]", "]", text)

    # Step 3: Fix Python literals (outside of strings — safe because values are after : )
    text = text.replace(": None", ": null")
    text = text.replace(": True", ": true")
    text = text.replace(": False", ": false")

    return text


def _extract_json_from_text(text: str) -> dict:
    """Extract JSON from LLM response text, handling markdown blocks and repairing if needed."""
    if not text or not text.strip():
        raise ValueError("Empty response text")

    raw = text.strip()

    # Handle markdown code blocks
    if "```json" in raw:
        start = raw.find("```json") + 7
        end = raw.find("```", start)
        raw = raw[start:end].strip()
    elif "```" in raw:
        start = raw.find("```") + 3
        end = raw.find("```", start)
        raw = raw[start:end].strip()
    elif "{" in raw and "}" in raw:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        raw = raw[start:end]

    # Try 1: Direct parse
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Try 2: Escape control chars then parse
    repaired = _repair_json(raw)
    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        pass

    # Try 3: Close truncated JSON (when Gemini hits max_tokens mid-output)
    closed = _close_truncated_json(repaired)
    try:
        result = json.loads(closed)
        logger.warning(f"JSON recovered via truncation repair (closed incomplete braces/strings)")
        return result
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse failed after all repairs. Error: {e}. First 500 chars: {raw[:500]}")
        raise


def _split_into_chunks(markdown: str, chunk_size: int = CHUNK_SIZE) -> List[str]:
    """
    Split markdown content into chunks, preferring document boundaries.

    Tries to split at '### Documento:' or '---' boundaries. Falls back to
    splitting at paragraph breaks ('\n\n').
    """
    if len(markdown) <= chunk_size:
        return [markdown]

    chunks = []
    remaining = markdown

    while remaining:
        if len(remaining) <= chunk_size:
            chunks.append(remaining)
            break

        # Try to find a document boundary within the chunk window
        window = remaining[:chunk_size]
        split_pos = None

        # Priority 1: Split at '### Documento:' boundary
        doc_markers = [m.start() for m in re.finditer(r"\n### Documento:", window)]
        if doc_markers:
            # Use the last document marker that gives us a reasonable chunk
            for marker in reversed(doc_markers):
                if marker > chunk_size * 0.3:  # At least 30% of target size
                    split_pos = marker
                    break

        # Priority 2: Split at '---' separator
        if split_pos is None:
            separators = [m.start() for m in re.finditer(r"\n---\n", window)]
            if separators:
                for sep in reversed(separators):
                    if sep > chunk_size * 0.3:
                        split_pos = sep
                        break

        # Priority 3: Split at paragraph break
        if split_pos is None:
            para_breaks = [m.start() for m in re.finditer(r"\n\n", window)]
            if para_breaks:
                split_pos = para_breaks[-1]

        # Fallback: hard cut
        if split_pos is None:
            split_pos = chunk_size

        chunks.append(remaining[:split_pos].strip())
        remaining = remaining[split_pos:].strip()

    return [c for c in chunks if c]


async def _call_llm_with_retry(
    llm,
    prompt: str,
    model: str,
    response_schema,
    max_retries: int = MAX_RETRIES,
    max_tokens: int = 8192,
) -> tuple[dict, LLMResponse]:
    """
    Call LLM with retry and temperature fallback.

    On JSON parse failure, retries with lower temperature and higher max_tokens
    to handle truncation caused by hitting the token limit.

    Returns (parsed_dict, raw_response).
    """
    last_error = None
    current_max_tokens = max_tokens

    for attempt in range(max_retries + 1):
        temperature = 0.1 if attempt == 0 else 0.0

        try:
            response: LLMResponse = await llm.agenerate(
                prompt=prompt,
                model=model,
                temperature=temperature,
                max_tokens=current_max_tokens,
                response_schema=response_schema,
            )

            data = _extract_json_from_text(response.text)
            return data, response

        except (json.JSONDecodeError, ValueError) as e:
            last_error = e
            # Check if output was likely truncated (output tokens near limit)
            if response.output_tokens >= current_max_tokens * 0.95:
                logger.warning(
                    f"LLM output likely truncated ({response.output_tokens}/{current_max_tokens} tokens). "
                    f"Retrying with higher limit."
                )
                current_max_tokens = min(current_max_tokens * 2, 32768)
            logger.warning(
                f"LLM JSON parse failed (attempt {attempt + 1}/{max_retries + 1}): {e}"
            )
            continue

    raise last_error  # type: ignore


async def _generate_direct(
    llm,
    full_prompt: str,
    model: str,
    provider: str,
) -> SummarizationResponse:
    """Direct summarization: single LLM call with retry."""
    data, response = await _call_llm_with_retry(
        llm=llm,
        prompt=full_prompt,
        model=model,
        response_schema=EditalSummaryLLMResponse,
    )

    summary = EditalSummaryLLMResponse(**data)
    cost = response.metadata.get("cost_usd", 0.0) if response.metadata else 0.0

    return SummarizationResponse(
        summary=summary,
        model=model,
        provider=provider,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        cost_usd=cost,
        success=True,
        strategy="direct",
    )


async def _map_single_chunk(
    llm,
    chunk_text: str,
    chunk_index: int,
    total_chunks: int,
    model: str,
) -> tuple[ChunkSummary, int, int]:
    """MAP pass: extract key info from a single chunk. Returns (summary, input_tokens, output_tokens)."""
    prompt = f"{MAP_SYSTEM_PROMPT}\n\n{build_map_prompt(chunk_text, chunk_index, total_chunks)}"

    data, response = await _call_llm_with_retry(
        llm=llm,
        prompt=prompt,
        model=model,
        response_schema=ChunkSummary,
        max_tokens=8192,
    )

    return ChunkSummary(**data), response.input_tokens, response.output_tokens


async def _generate_map_reduce(
    llm,
    markdown_content: str,
    metadata_dict: dict,
    items_text: str,
    model: str,
    provider: str,
) -> SummarizationResponse:
    """Map-Reduce summarization: chunk → MAP each → REDUCE into final summary."""
    chunks = _split_into_chunks(markdown_content)
    total_chunks = len(chunks)
    logger.info(f"Map-Reduce: splitting {len(markdown_content)} chars into {total_chunks} chunks")

    # MAP phase: summarize each chunk in parallel
    tasks = [
        _map_single_chunk(llm, chunk, i, total_chunks, model)
        for i, chunk in enumerate(chunks)
    ]
    map_results = await asyncio.gather(*tasks, return_exceptions=True)

    chunk_summaries = []
    total_input = 0
    total_output = 0

    for i, result in enumerate(map_results):
        if isinstance(result, Exception):
            logger.error(f"MAP chunk {i + 1}/{total_chunks} failed: {result}")
            continue
        summary, inp, out = result
        chunk_summaries.append(summary)
        total_input += inp
        total_output += out

    if not chunk_summaries:
        raise ValueError("All MAP chunks failed — no data extracted")

    logger.info(f"MAP complete: {len(chunk_summaries)}/{total_chunks} chunks succeeded")

    # REDUCE phase: consolidate into final summary
    chunk_summaries_json = json.dumps(
        [cs.model_dump(exclude_none=True) for cs in chunk_summaries],
        ensure_ascii=False,
        indent=2,
    )

    reduce_prompt = (
        f"{REDUCE_SYSTEM_PROMPT}\n\n"
        f"{build_reduce_prompt(chunk_summaries_json, metadata_dict, items_text)}"
    )

    data, reduce_response = await _call_llm_with_retry(
        llm=llm,
        prompt=reduce_prompt,
        model=model,
        response_schema=EditalSummaryLLMResponse,
    )

    total_input += reduce_response.input_tokens
    total_output += reduce_response.output_tokens

    summary = EditalSummaryLLMResponse(**data)

    # Calculate total cost
    total_cost = 0.0
    if reduce_response.metadata:
        # Use the pricing from the reduce call's model
        cost_per_1m_input = 0.15  # gemini-2.5-flash
        cost_per_1m_output = 0.60
        total_cost = (total_input / 1_000_000 * cost_per_1m_input) + (
            total_output / 1_000_000 * cost_per_1m_output
        )

    return SummarizationResponse(
        summary=summary,
        model=model,
        provider=provider,
        input_tokens=total_input,
        output_tokens=total_output,
        cost_usd=total_cost,
        success=True,
        strategy="map_reduce",
        chunks_processed=len(chunk_summaries),
    )


async def generate_summary(
    request: Union[SummarizationRequest, dict],
    provider: str = DEFAULT_PROVIDER,
    model: Optional[str] = None,
) -> SummarizationResponse:
    """
    Generate a comprehensive edital summary.

    Automatically selects strategy:
    - Direct: for documents < 80K chars (single LLM call with retry)
    - Map-Reduce: for documents >= 80K chars (chunk → MAP → REDUCE)

    Args:
        request: Summarization request with metadata + markdown content
        provider: LLM provider name
        model: Model to use (defaults to gemini-2.5-flash)

    Returns:
        SummarizationResponse with structured summary + metadata
    """
    if isinstance(request, dict):
        request = SummarizationRequest(**request)

    # Use request-level overrides if provided
    provider = request.provider or provider
    model = request.model or model or DEFAULT_SUMMARIZATION_MODEL

    metadata_dict = request.edital_metadata.model_dump()
    items_text = format_items(
        [item.model_dump() for item in request.edital_metadata.itens]
    )
    markdown_content = request.markdown_content or ""

    try:
        llm = create_provider(provider)

        content_length = len(markdown_content)
        logger.info(
            f"Summarizing edital: {content_length} chars markdown, "
            f"model={model}, threshold={MAP_REDUCE_THRESHOLD}"
        )

        if content_length >= MAP_REDUCE_THRESHOLD:
            # Map-Reduce strategy for large documents
            return await _generate_map_reduce(
                llm=llm,
                markdown_content=markdown_content,
                metadata_dict=metadata_dict,
                items_text=items_text,
                model=model,
                provider=provider,
            )
        else:
            # Direct strategy for smaller documents
            user_prompt = build_user_prompt(
                metadata=metadata_dict,
                items_text=items_text,
                markdown_content=markdown_content,
            )
            full_prompt = f"{SYSTEM_PROMPT}\n\n{user_prompt}"

            return await _generate_direct(
                llm=llm,
                full_prompt=full_prompt,
                model=model,
                provider=provider,
            )

    except Exception as e:
        logger.error(f"Edital summarization failed: {e}", exc_info=True)
        return SummarizationResponse(
            summary=EditalSummaryLLMResponse(),
            model=model,
            provider=provider,
            success=False,
            error=str(e),
        )



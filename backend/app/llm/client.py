"""Wrapped AsyncOpenAI client with caching, retries, and DB logging.

Every LLM call in the pipeline goes through `parse()` here. That gives us:
  - Prompt-hash caching (diskcache) — same input never charged twice.
  - Automatic retries (tenacity) on transient errors with exponential backoff.
  - An `llm_calls` row per call so we can audit cost + latency + cache hits.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any, TypeVar

from diskcache import Cache
from openai import (
    APIConnectionError,
    APITimeoutError,
    AsyncOpenAI,
    InternalServerError,
    RateLimitError,
)
from pydantic import BaseModel
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import settings
from app.db.session import SessionLocal
from app.db.tables import LlmCall
from app.llm.pricing import estimate_cost
from app.models.enums import LlmPurpose

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_CACHE_DIR = "/app/.cache/llm"
_cache = Cache(_CACHE_DIR)

_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    """Lazy-init the AsyncOpenAI client so import-time doesn't explode
    when the key is missing (useful for tests and rule-based fallbacks)."""
    global _client
    if _client is None:
        if not settings.openai_api_key or settings.openai_api_key.startswith("sk-replace"):
            raise RuntimeError(
                "OPENAI_API_KEY is not set. "
                "Set it in .env to use the LLM client."
            )
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


def has_api_key() -> bool:
    return bool(
        settings.openai_api_key and not settings.openai_api_key.startswith("sk-replace")
    )


def _hash_request(
    model: str, messages: list[dict[str, Any]], schema: dict[str, Any]
) -> str:
    payload = json.dumps(
        {"model": model, "messages": messages, "schema": schema},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@retry(
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_attempt(4),
    retry=retry_if_exception_type(
        (RateLimitError, APIConnectionError, APITimeoutError, InternalServerError)
    ),
    reraise=True,
)
async def _parse_with_retries(
    model: str,
    messages: list[dict[str, Any]],
    response_format: type[BaseModel],
):
    client = get_client()
    return await client.chat.completions.parse(
        model=model,
        messages=messages,
        response_format=response_format,
    )


async def _log_call(
    *,
    case_id: int | None,
    purpose: LlmPurpose,
    model: str,
    prompt_hash: str,
    cache_hit: bool,
    success: bool,
    latency_ms: int,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    error: str | None = None,
) -> None:
    cost = estimate_cost(model, prompt_tokens, completion_tokens)
    async with SessionLocal() as session:
        row = LlmCall(
            case_id=case_id,
            purpose=purpose.value,
            model=model,
            prompt_hash=prompt_hash,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost,
            latency_ms=latency_ms,
            cache_hit=cache_hit,
            success=success,
            error=error,
        )
        session.add(row)
        await session.commit()


async def embed(
    *,
    texts: list[str],
    model: str | None = None,
    case_id: int | None = None,
) -> list[list[float]]:
    """Embed texts with OpenAI. Per-text cached; batch-called per miss set.

    Returns one embedding per input text. Order preserved.
    If the API key is not set, returns zero-vectors of the correct dim so
    downstream indexing still succeeds (search will be useless but won't crash).
    """
    model = model or settings.embedding_model
    dim = 1536  # text-embedding-3-small default; fine for our chunks table column

    if not texts:
        return []

    # Per-text cache lookup
    results: list[list[float] | None] = [None] * len(texts)
    miss_indices: list[int] = []
    miss_texts: list[str] = []
    for i, text in enumerate(texts):
        key = _hash_request(model, [{"embed": text}], {})
        if key in _cache:
            results[i] = _cache[key]
        else:
            miss_indices.append(i)
            miss_texts.append(text)

    if not miss_texts:
        return [r if r is not None else [0.0] * dim for r in results]

    if not has_api_key():
        # Dev fallback: return zeros so the pipeline still runs without a key.
        for i in miss_indices:
            results[i] = [0.0] * dim
        return [r if r is not None else [0.0] * dim for r in results]

    client = get_client()
    start = time.monotonic()
    try:
        response = await client.embeddings.create(model=model, input=miss_texts)
        latency_ms = int((time.monotonic() - start) * 1000)
        total_tokens = response.usage.total_tokens if response.usage else None

        for local_i, d in enumerate(response.data):
            orig_i = miss_indices[local_i]
            vec = list(d.embedding)
            results[orig_i] = vec
            key = _hash_request(model, [{"embed": miss_texts[local_i]}], {})
            _cache[key] = vec

        await _log_call(
            case_id=case_id,
            purpose=LlmPurpose.embed,
            model=model,
            prompt_hash=hashlib.sha256(
                ("|".join(miss_texts)).encode("utf-8")
            ).hexdigest(),
            cache_hit=False,
            success=True,
            latency_ms=latency_ms,
            prompt_tokens=total_tokens,
        )
    except Exception as e:
        latency_ms = int((time.monotonic() - start) * 1000)
        log.exception("Embeddings call failed: model=%s", model)
        await _log_call(
            case_id=case_id,
            purpose=LlmPurpose.embed,
            model=model,
            prompt_hash="",
            cache_hit=False,
            success=False,
            latency_ms=latency_ms,
            error=str(e)[:500],
        )
        raise

    return [r if r is not None else [0.0] * dim for r in results]


async def parse(
    *,
    purpose: LlmPurpose,
    model: str,
    messages: list[dict[str, Any]],
    response_format: type[T],
    case_id: int | None = None,
) -> T:
    """Execute a chat completion, auto-parse into the given Pydantic model.

    Cached by (model, messages, schema). Logged to `llm_calls` either way.
    """
    schema = response_format.model_json_schema()
    prompt_hash = _hash_request(model, messages, schema)

    start = time.monotonic()

    # Cache hit
    if prompt_hash in _cache:
        cached: dict = _cache[prompt_hash]  # type: ignore[assignment]
        latency_ms = int((time.monotonic() - start) * 1000)
        await _log_call(
            case_id=case_id,
            purpose=purpose,
            model=model,
            prompt_hash=prompt_hash,
            cache_hit=True,
            success=True,
            latency_ms=latency_ms,
        )
        return response_format.model_validate(cached)

    # Live call
    try:
        completion = await _parse_with_retries(model, messages, response_format)
        message = completion.choices[0].message
        parsed = message.parsed
        if parsed is None:
            raise ValueError(
                f"Model refused to produce structured output: {message.refusal}"
            )

        _cache[prompt_hash] = parsed.model_dump()

        latency_ms = int((time.monotonic() - start) * 1000)
        usage = completion.usage
        await _log_call(
            case_id=case_id,
            purpose=purpose,
            model=model,
            prompt_hash=prompt_hash,
            cache_hit=False,
            success=True,
            latency_ms=latency_ms,
            prompt_tokens=usage.prompt_tokens if usage else None,
            completion_tokens=usage.completion_tokens if usage else None,
        )
        return parsed  # type: ignore[return-value]

    except Exception as e:
        latency_ms = int((time.monotonic() - start) * 1000)
        log.exception("LLM call failed: model=%s purpose=%s", model, purpose)
        await _log_call(
            case_id=case_id,
            purpose=purpose,
            model=model,
            prompt_hash=prompt_hash,
            cache_hit=False,
            success=False,
            latency_ms=latency_ms,
            error=str(e)[:500],
        )
        raise

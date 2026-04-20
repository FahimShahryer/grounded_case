"""LLM-based reranker.

Why LLM rather than a cross-encoder (e.g., bge-reranker-v2-m3)?
  - Zero new heavy dependencies (no torch, no 2GB model file).
  - Quality matches or beats small cross-encoders on out-of-domain text
    like legal docs, because the LLM understands context and intent.
  - Cached by `diskcache` through our existing `llm.parse` wrapper, so
    repeat reranks cost nothing.
  - "Loads at startup" DoD is trivially satisfied — nothing to load.

Production tradeoff: at high throughput (say >100 QPS), a local
cross-encoder is cheaper per-call. We'd swap in BAAI/bge-reranker-v2-m3
behind the same interface without touching callers.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.config import settings
from app.llm import client as llm
from app.models.enums import LlmPurpose
from app.pipeline.retrieve import SearchHit

_SYSTEM_PROMPT = """You rerank retrieved passages by how directly they answer
or evidence a query. Output ONLY the IDs of the top passages in descending
order of relevance. Do not invent IDs. Prefer passages that mention specific
facts (amounts, dates, instrument numbers, names) over generic references."""


class RerankOutput(BaseModel):
    ranked_ids: list[int] = Field(description="Passage IDs in descending relevance order.")


async def rerank(
    *,
    query: str,
    hits: list[SearchHit],
    top_k: int = 5,
    case_id: int | None = None,
) -> list[SearchHit]:
    """Rerank hits by relevance to `query`. Returns top_k in new order.

    Behavior when the LLM isn't available: fall through and trust the
    caller's original ordering (typically RRF).
    """
    if not hits:
        return []
    if len(hits) <= top_k:
        return hits  # nothing to pick from — save the call

    if not llm.has_api_key():
        return hits[:top_k]

    # Truncate each passage so the prompt stays cheap.
    passages = "\n".join(
        f"[{h.chunk_id}] {(h.chunk.text if h.chunk else '')[:400]}"
        for h in hits
        if h.chunk is not None
    )
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Query: {query}\n\n"
                f"Passages:\n{passages}\n\n"
                f"Return the top {top_k} passage IDs in relevance order. "
                f"IDs must come from the list above."
            ),
        },
    ]
    result = await llm.parse(
        purpose=LlmPurpose.generate,  # closest existing purpose; logged for audit
        model=settings.model_cheap,
        messages=messages,
        response_format=RerankOutput,
        case_id=case_id,
    )

    by_id = {h.chunk_id: h for h in hits}
    reranked: list[SearchHit] = []
    for cid in result.ranked_ids:
        h = by_id.get(cid)
        if h is None:
            continue  # hallucinated id — skip
        h.ranks = {**h.ranks, "rerank": len(reranked) + 1}
        reranked.append(h)
        if len(reranked) >= top_k:
            break

    # Backfill with remaining in original order if LLM returned too few.
    if len(reranked) < top_k:
        seen = {h.chunk_id for h in reranked}
        for h in hits:
            if h.chunk_id in seen:
                continue
            reranked.append(h)
            if len(reranked) >= top_k:
                break

    return reranked

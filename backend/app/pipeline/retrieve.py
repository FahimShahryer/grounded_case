"""Search retrieval: BM25, vector, and hybrid (Reciprocal Rank Fusion).

This is the raw retrieval layer — returns ranked chunks with scores.
Step 6 will build EvidencePacks on top with query planning and reranking.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.tables import Chunk
from app.llm import client as llm
from app.pipeline.bm25_store import bm25_store, tokenize

# Reciprocal Rank Fusion constant (Cormack et al. 2009 recommend 60).
RRF_K = 60


@dataclass
class SearchHit:
    chunk_id: int
    score: float
    source: str  # "bm25" | "vector" | "hybrid"
    chunk: Chunk | None = None
    # per-source ranks (debug)
    ranks: dict[str, int] = field(default_factory=dict)


async def bm25_search(
    case_id: int, query: str, session: AsyncSession, top_k: int = 10
) -> list[SearchHit]:
    index = await bm25_store.get(case_id, session)
    if not index.chunks:
        return []

    scores = index.bm25.get_scores(tokenize(query))
    ranked = sorted(enumerate(scores), key=lambda kv: kv[1], reverse=True)
    hits: list[SearchHit] = []
    for rank, (i, s) in enumerate(ranked, start=1):
        if s <= 0:
            break
        chunk = index.chunks[i]
        hits.append(
            SearchHit(
                chunk_id=chunk.id,
                score=float(s),
                source="bm25",
                chunk=chunk,
                ranks={"bm25": rank},
            )
        )
        if len(hits) >= top_k:
            break
    return hits


async def vector_search(
    case_id: int, query: str, session: AsyncSession, top_k: int = 10
) -> list[SearchHit]:
    query_vec = (await llm.embed(texts=[query], case_id=case_id))[0]

    # cosine_distance: 0 = identical, 2 = opposite. Lower is better.
    stmt = (
        select(
            Chunk,
            Chunk.embedding.cosine_distance(query_vec).label("distance"),
        )
        .where(Chunk.case_id == case_id, Chunk.embedding.is_not(None))
        .order_by("distance")
        .limit(top_k)
    )
    rows = (await session.execute(stmt)).all()

    return [
        SearchHit(
            chunk_id=chunk.id,
            score=float(1 - float(distance)),  # cosine similarity for display
            source="vector",
            chunk=chunk,
            ranks={"vector": rank},
        )
        for rank, (chunk, distance) in enumerate(rows, start=1)
    ]


async def hybrid_search(
    case_id: int, query: str, session: AsyncSession, top_k: int = 5
) -> list[SearchHit]:
    """Reciprocal Rank Fusion of BM25 + vector results."""
    pool = max(top_k * 4, 10)
    bm25_hits = await bm25_search(case_id, query, session, top_k=pool)
    vec_hits = await vector_search(case_id, query, session, top_k=pool)

    rrf_scores: dict[int, float] = {}
    ranks_by_chunk: dict[int, dict[str, int]] = {}
    chunk_by_id: dict[int, Chunk] = {}

    for hit in bm25_hits:
        rank = hit.ranks["bm25"]
        rrf_scores[hit.chunk_id] = rrf_scores.get(hit.chunk_id, 0) + 1.0 / (RRF_K + rank)
        ranks_by_chunk.setdefault(hit.chunk_id, {})["bm25"] = rank
        if hit.chunk is not None:
            chunk_by_id[hit.chunk_id] = hit.chunk

    for hit in vec_hits:
        rank = hit.ranks["vector"]
        rrf_scores[hit.chunk_id] = rrf_scores.get(hit.chunk_id, 0) + 1.0 / (RRF_K + rank)
        ranks_by_chunk.setdefault(hit.chunk_id, {})["vector"] = rank
        if hit.chunk is not None:
            chunk_by_id[hit.chunk_id] = hit.chunk

    ordered_ids = sorted(rrf_scores, key=lambda c: rrf_scores[c], reverse=True)[:top_k]
    return [
        SearchHit(
            chunk_id=cid,
            score=rrf_scores[cid],
            source="hybrid",
            chunk=chunk_by_id.get(cid),
            ranks=ranks_by_chunk.get(cid, {}),
        )
        for cid in ordered_ids
    ]


async def search(
    case_id: int,
    query: str,
    session: AsyncSession,
    mode: str = "hybrid",
    top_k: int = 5,
) -> list[SearchHit]:
    if mode == "bm25":
        return await bm25_search(case_id, query, session, top_k)
    if mode == "vector":
        return await vector_search(case_id, query, session, top_k)
    if mode == "hybrid":
        return await hybrid_search(case_id, query, session, top_k)
    raise ValueError(f"Unknown search mode: {mode!r}")

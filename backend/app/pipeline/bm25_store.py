"""In-process BM25 index keyed by case_id.

Lazy: built on first search for a case and cached until explicitly
invalidated (e.g., after re-indexing). For larger deployments this would
become a distributed service (Elasticsearch/OpenSearch); at our scale
in-memory is sharper and dependency-free.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from rank_bm25 import BM25Okapi
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.tables import Chunk

_TOKEN_RE = re.compile(r"[\w-]+")


def tokenize(text: str) -> list[str]:
    """Lowercase + keep alphanumeric tokens and hyphens.

    Hyphens matter: instrument numbers like `2021-0123456` must remain
    one token (or at least be searchable as a prefix/substring).
    """
    return [t for t in _TOKEN_RE.findall(text.lower()) if t]


@dataclass
class BM25Index:
    bm25: BM25Okapi
    chunks: list[Chunk]


class BM25Store:
    def __init__(self) -> None:
        self._by_case: dict[int, BM25Index] = {}

    def invalidate(self, case_id: int) -> None:
        self._by_case.pop(case_id, None)

    def invalidate_all(self) -> None:
        self._by_case.clear()

    async def get(self, case_id: int, session: AsyncSession) -> BM25Index:
        hit = self._by_case.get(case_id)
        if hit is not None:
            return hit

        rows = (
            (
                await session.execute(
                    select(Chunk).where(Chunk.case_id == case_id).order_by(Chunk.id)
                )
            )
            .scalars()
            .all()
        )
        if not rows:
            # Empty index — return a trivial placeholder; callers should check len(chunks).
            index = BM25Index(bm25=BM25Okapi([[""]]), chunks=[])
        else:
            tokenized = [tokenize(c.text) for c in rows]
            index = BM25Index(bm25=BM25Okapi(tokenized), chunks=list(rows))

        self._by_case[case_id] = index
        return index


bm25_store = BM25Store()

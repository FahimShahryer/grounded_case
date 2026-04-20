"""Indexing: chunk every document in a case, embed, persist, invalidate BM25."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.tables import Chunk, Document
from app.llm import client as llm
from app.pipeline.bm25_store import bm25_store
from app.pipeline.chunk import chunk_document

__all__ = ["IndexResult", "index_case"]


@dataclass
class IndexResult:
    chunks_created: int = 0
    chunks_embedded: int = 0


async def _chunk_documents(case_id: int, session: AsyncSession) -> int:
    """Delete existing chunks for the case and recompute from current documents."""
    await session.execute(delete(Chunk).where(Chunk.case_id == case_id))

    docs = (
        (await session.execute(select(Document).where(Document.case_id == case_id)))
        .scalars()
        .all()
    )

    created = 0
    for doc in docs:
        source_text = doc.cleaned_text or doc.raw_text
        pieces = chunk_document(source_text, doc.doc_type)
        for i, piece in enumerate(pieces):
            session.add(
                Chunk(
                    case_id=case_id,
                    document_id=doc.id,
                    chunk_index=i,
                    text=piece.text,
                    line_start=piece.line_start,
                    line_end=piece.line_end,
                    section_header=piece.section_header,
                    doc_type=doc.doc_type,
                    metadata_json={
                        "filename": doc.filename,
                    },
                    embedding=None,
                )
            )
            created += 1

    await session.commit()
    return created


async def _embed_chunks(case_id: int, session: AsyncSession) -> int:
    """Embed every chunk in the case that is missing an embedding."""
    rows = (
        (
            await session.execute(
                select(Chunk)
                .where(Chunk.case_id == case_id, Chunk.embedding.is_(None))
                .order_by(Chunk.id)
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return 0

    # OpenAI embeddings accept batched input; 100-at-a-time is safe.
    BATCH = 100
    embedded = 0
    for i in range(0, len(rows), BATCH):
        batch = rows[i : i + BATCH]
        vectors = await llm.embed(texts=[c.text for c in batch], case_id=case_id)
        for chunk, vec in zip(batch, vectors, strict=True):
            chunk.embedding = vec
        await session.commit()
        embedded += len(batch)
    return embedded


async def index_case(case_id: int, session: AsyncSession) -> IndexResult:
    """Rebuild chunks + embeddings for a case. Invalidates the BM25 cache."""
    created = await _chunk_documents(case_id, session)
    embedded = await _embed_chunks(case_id, session)
    bm25_store.invalidate(case_id)
    return IndexResult(chunks_created=created, chunks_embedded=embedded)

"""Indexing + search endpoints."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.deps import SessionDep
from app.db.tables import Case
from app.pipeline.index import index_case
from app.pipeline.retrieve import search

router = APIRouter(prefix="/api/cases/{case_id}", tags=["search"])


class IndexResponse(BaseModel):
    case_id: int
    chunks_created: int
    chunks_embedded: int


class SearchHitOut(BaseModel):
    chunk_id: int
    score: float
    source: str
    document_id: int
    filename: str
    doc_type: str
    line_start: int | None
    line_end: int | None
    section_header: str | None
    text: str
    ranks: dict[str, int] = Field(default_factory=dict)


@router.post("/index", response_model=IndexResponse)
async def rebuild_index(case_id: int, session: SessionDep) -> IndexResponse:
    case = await session.get(Case, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    result = await index_case(case_id, session)
    return IndexResponse(
        case_id=case_id,
        chunks_created=result.chunks_created,
        chunks_embedded=result.chunks_embedded,
    )


@router.get("/search", response_model=list[SearchHitOut])
async def search_case(
    case_id: int,
    session: SessionDep,
    q: str = Query(..., description="Query string"),
    mode: Literal["bm25", "vector", "hybrid"] = "hybrid",
    top_k: int = Query(default=5, ge=1, le=50),
) -> list[SearchHitOut]:
    case = await session.get(Case, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    hits = await search(case_id, q, session, mode=mode, top_k=top_k)

    out: list[SearchHitOut] = []
    for h in hits:
        if h.chunk is None:
            continue
        out.append(
            SearchHitOut(
                chunk_id=h.chunk_id,
                score=h.score,
                source=h.source,
                document_id=h.chunk.document_id,
                filename=(h.chunk.metadata_json or {}).get("filename", ""),
                doc_type=h.chunk.doc_type,
                line_start=h.chunk.line_start,
                line_end=h.chunk.line_end,
                section_header=h.chunk.section_header,
                text=h.chunk.text,
                ranks=h.ranks,
            )
        )
    return out

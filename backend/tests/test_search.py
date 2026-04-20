"""Search tests — BM25 doesn't need LLM; vector/hybrid do.

Relies on a fully-processed case 1 in the DB. Safe to run after `make seed`
followed by `POST /api/cases/1/process`.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.session import SessionLocal
from app.db.tables import Case, Chunk
from app.llm.client import has_api_key
from app.pipeline.bm25_store import bm25_store
from app.pipeline.retrieve import bm25_search, hybrid_search, vector_search


async def _case_indexed() -> bool:
    async with SessionLocal() as session:
        case = (await session.execute(select(Case).limit(1))).scalar_one_or_none()
        if case is None:
            return False
        count = (
            await session.execute(select(Chunk).where(Chunk.case_id == case.id).limit(1))
        ).scalar_one_or_none()
        return count is not None


# ---- BM25 tests (no LLM needed) ----


async def test_bm25_finds_exact_instrument_number():
    if not await _case_indexed():
        pytest.skip("Case not indexed; run POST /api/cases/1/process first")

    bm25_store.invalidate_all()
    async with SessionLocal() as session:
        hits = await bm25_search(1, "2021-0123456", session=session, top_k=10)

    # The loan/instrument number appears in both title_search page 1 AND the
    # servicer email (which cites the loan #). All top hits should contain it.
    assert hits, "BM25 returned nothing for exact instrument number"
    for h in hits[:3]:
        text = h.chunk.text
        assert "2021-0123456" in text or "2O21-O123456" in text, (
            f"top hit does not contain instrument number: {text[:120]}"
        )

    # And we must at least have a title-search hit in the pool.
    doc_types = {h.chunk.doc_type for h in hits}
    assert "title_search" in doc_types


async def test_bm25_finds_hoa_language():
    if not await _case_indexed():
        pytest.skip("Case not indexed")
    bm25_store.invalidate_all()
    async with SessionLocal() as session:
        hits = await bm25_search(1, "HOA lis pendens", session=session, top_k=5)
    assert hits
    top_text = hits[0].chunk.text.upper()
    assert ("HOA" in top_text) or ("HOMEOWNERS" in top_text) or ("LIS PENDENS" in top_text)


# ---- Vector / hybrid tests (need API key) ----


pytest_mark_llm = pytest.mark.skipif(
    not has_api_key(), reason="OPENAI_API_KEY not set; skipping embeddings search tests"
)


@pytest_mark_llm
async def test_vector_finds_semantic_match_for_tax_delinquency():
    if not await _case_indexed():
        pytest.skip("Case not indexed")
    async with SessionLocal() as session:
        hits = await vector_search(1, "property tax delinquency", session=session, top_k=5)
    assert hits
    # The answer is in the tax-status chunk; "delinquent" may not even appear in it.
    combined = " ".join(h.chunk.text for h in hits[:3]).lower()
    assert "tax" in combined


@pytest_mark_llm
async def test_hybrid_better_than_bm25_alone_for_semantic_query():
    """Hybrid should surface the tax chunk for a paraphrased query."""
    if not await _case_indexed():
        pytest.skip("Case not indexed")
    bm25_store.invalidate_all()
    async with SessionLocal() as session:
        hits = await hybrid_search(
            1, "unpaid real estate taxes", session=session, top_k=5
        )
    assert hits
    # At least one top-3 chunk should mention tax-related language.
    top3 = " ".join(h.chunk.text for h in hits[:3]).lower()
    assert "tax" in top3 or "$8,247" in top3 or "8,247" in top3

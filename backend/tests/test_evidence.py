"""Evidence-pack builder tests.

Need a fully-processed case 1 — run `POST /api/cases/1/process` first.
The reranker step calls the LLM; diskcache makes repeat runs free.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.session import SessionLocal
from app.db.tables import Case, Chunk
from app.llm.client import has_api_key
from app.models.enums import DraftType
from app.pipeline.evidence import build_evidence_pack
from app.pipeline.plans import plan_for


async def _indexed_case_id() -> int | None:
    async with SessionLocal() as session:
        case = (await session.execute(select(Case).limit(1))).scalar_one_or_none()
        if case is None:
            return None
        has_chunks = (
            await session.execute(select(Chunk).where(Chunk.case_id == case.id).limit(1))
        ).scalar_one_or_none()
        return case.id if has_chunks is not None else None


pytestmark = pytest.mark.skipif(
    not has_api_key(),
    reason="OPENAI_API_KEY not set; evidence packs use the LLM reranker",
)


def _section(plan, section_id):
    return next(s for s in plan.sections if s.section_id == section_id)


async def test_liens_pack_contains_wells_fargo_hoa_and_assignment():
    case_id = await _indexed_case_id()
    if case_id is None:
        pytest.skip("Case not indexed; run POST /api/cases/1/process first")

    plan = plan_for(DraftType.title_review_summary)
    async with SessionLocal() as session:
        pack = await build_evidence_pack(case_id, _section(plan, "liens"), session)

    assert pack.structured_facts, "expected lien facts in graph"
    creditors = [(f.payload.get("creditor") or "").upper() for f in pack.structured_facts]
    joined = " | ".join(creditors)
    assert "WELLS FARGO" in joined, f"Wells Fargo missing: {joined}"
    assert any("NATIONSTAR" in c or "COOPER" in c for c in creditors), (
        f"assignment (Nationstar/Mr. Cooper) missing: {joined}"
    )
    assert any("HOA" in c or "HOMEOWNERS" in c or "PALMETTO" in c for c in creditors), (
        f"HOA lis pendens missing: {joined}"
    )

    # Every structured fact must carry at least one source span (citability).
    for f in pack.structured_facts:
        assert f.evidence_spans, f"lien fact {f.dedup_key} has no evidence spans"


async def test_deadlines_pack_pulls_from_multiple_documents():
    case_id = await _indexed_case_id()
    if case_id is None:
        pytest.skip("Case not indexed")

    plan = plan_for(DraftType.case_status_memo)
    async with SessionLocal() as session:
        pack = await build_evidence_pack(case_id, _section(plan, "deadlines"), session)

    # Deadlines come from court_order (filing deadlines + case management conference).
    sources = {e.filename for e in pack.text_evidence}
    assert any("court_order" in s for s in sources), f"court_order missing from: {sources}"

    # And we should have structured deadline/filing facts.
    types = {f.fact_type for f in pack.structured_facts}
    assert {"deadline", "filing_requirement", "appearance"} & types


async def test_judgments_pack_yields_known_gap():
    """The Rodriguez case has no judgments → pack's known_gaps should say so."""
    case_id = await _indexed_case_id()
    if case_id is None:
        pytest.skip("Case not indexed")

    plan = plan_for(DraftType.title_review_summary)
    async with SessionLocal() as session:
        pack = await build_evidence_pack(case_id, _section(plan, "judgments"), session)

    assert not pack.structured_facts, "no 'judgment' facts should exist in our sample"
    assert pack.known_gaps, "expected a known_gap for missing judgment facts"
    assert any("judgment" in g.lower() for g in pack.known_gaps)

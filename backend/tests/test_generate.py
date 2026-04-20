"""Draft-generation tests.

Assumes Rodriguez case is fully processed (POST /api/cases/1/process).
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.session import SessionLocal
from app.db.tables import Case, Chunk
from app.llm.client import has_api_key
from app.models.common import SourceSpan
from app.models.draft import Citation, DraftBlock, DraftSection, FieldLine
from app.models.enums import DraftType
from app.models.evidence_pack import EvidenceChunk, EvidencePack
from app.pipeline.generate import generate_draft, render_draft_markdown
from app.pipeline.generate.verify import verify_deterministic


async def _indexed_case_id() -> int | None:
    async with SessionLocal() as session:
        case = (await session.execute(select(Case).limit(1))).scalar_one_or_none()
        if case is None:
            return None
        has_chunks = (
            await session.execute(select(Chunk).where(Chunk.case_id == case.id).limit(1))
        ).scalar_one_or_none()
        return case.id if has_chunks is not None else None


# -------- deterministic verifier (no LLM) ----------------------------------


def test_verifier_rejects_block_without_citation():
    ev = EvidencePack(
        section_id="liens",
        description="Liens",
        text_evidence=[
            EvidenceChunk(
                chunk_id=1,
                document_id=1,
                filename="title_search_page1.txt",
                doc_type="title_search",
                line_start=16,
                line_end=19,
                section_header="2.",
                text="Mortgage from Rodriguez to Wells Fargo",
                score=1.0,
            )
        ],
    )
    bad_section = DraftSection(
        id="liens",
        heading="Liens",
        blocks=[
            DraftBlock(
                title="First Mortgage",
                fields=[FieldLine(key="amount", value="$445,000")],
                citations=[],  # ← missing citation
            )
        ],
    )
    result = verify_deterministic(bad_section, ev)
    assert not result.all_supported
    assert any("no citations" in issue.lower() for issue in result.unsupported_claims)


def test_verifier_rejects_citation_to_unknown_file():
    ev = EvidencePack(
        section_id="liens",
        description="Liens",
        text_evidence=[
            EvidenceChunk(
                chunk_id=1,
                document_id=1,
                filename="title_search_page1.txt",
                doc_type="title_search",
                line_start=16,
                line_end=19,
                section_header="2.",
                text="Mortgage...",
                score=1.0,
            )
        ],
    )
    section = DraftSection(
        id="liens",
        heading="Liens",
        blocks=[
            DraftBlock(
                title="Made up",
                fields=[FieldLine(key="x", value="y")],
                citations=[
                    Citation(
                        claim="something",
                        spans=[
                            SourceSpan(
                                file="MADE_UP.txt",  # ← not in evidence pack
                                line_start=1,
                                line_end=1,
                                raw_text="fake",
                            )
                        ],
                    )
                ],
            )
        ],
    )
    result = verify_deterministic(section, ev)
    assert not result.all_supported
    assert any("MADE_UP.txt" in issue for issue in result.unsupported_claims)


def test_verifier_accepts_good_section():
    ev = EvidencePack(
        section_id="liens",
        description="Liens",
        text_evidence=[
            EvidenceChunk(
                chunk_id=1,
                document_id=1,
                filename="title_search_page1.txt",
                doc_type="title_search",
                line_start=16,
                line_end=19,
                section_header="2.",
                text="Mortgage from Rodriguez to Wells Fargo",
                score=1.0,
            )
        ],
    )
    section = DraftSection(
        id="liens",
        heading="Liens",
        blocks=[
            DraftBlock(
                title="First Mortgage",
                fields=[FieldLine(key="amount", value="$445,000")],
                citations=[
                    Citation(
                        claim="$445,000 Wells Fargo mortgage",
                        spans=[
                            SourceSpan(
                                file="title_search_page1.txt",
                                line_start=16,
                                line_end=19,
                                raw_text="Mortgage from Rodriguez to Wells Fargo",
                            )
                        ],
                    )
                ],
            )
        ],
    )
    result = verify_deterministic(section, ev)
    assert result.all_supported
    assert not result.unsupported_claims


# -------- end-to-end draft (LLM required) ---------------------------------


pytestmark_llm = pytest.mark.skipif(
    not has_api_key(), reason="OPENAI_API_KEY not set; skipping end-to-end draft test"
)


@pytestmark_llm
async def test_title_review_draft_end_to_end():
    case_id = await _indexed_case_id()
    if case_id is None:
        pytest.skip("Case not processed; POST /api/cases/1/process first")

    async with SessionLocal() as session:
        draft = await generate_draft(
            case_id=case_id, draft_type=DraftType.title_review_summary, session=session
        )

    assert draft.id
    assert draft.content_markdown
    assert "Title Review Summary" in draft.content_markdown
    assert "Rodriguez" in draft.content_markdown

    content = draft.content
    section_ids = [s["id"] for s in content["sections"]]
    assert {"liens", "tax_status", "ownership", "judgments"} <= set(section_ids)

    # Grounding check: every non-abstained section with content-bearing
    # blocks must carry citations SOMEWHERE — either on the blocks
    # themselves or at the section level. This catches fabrication (no
    # source anywhere) without locking the LLM into a specific citation
    # placement (header-block + data sub-blocks is a legitimate shape).
    for section in content["sections"]:
        if section.get("abstained"):
            continue
        blocks = section.get("blocks") or []
        has_content = any(
            b.get("fields") or b.get("notes") or b.get("action_items")
            for b in blocks
        )
        if not has_content:
            continue
        block_cites = any(b.get("citations") for b in blocks)
        section_cites = bool(section.get("citations"))
        assert block_cites or section_cites, (
            f"section {section.get('id')!r} has content but no citations "
            f"on any block and no section-level citations either"
        )


@pytestmark_llm
async def test_judgments_section_abstains_or_cites_grounded():
    """Sample has no judgment facts. The judgments section must not
    FABRICATE — either abstain, acknowledge absence, or back every
    block with a real citation (i.e. every claim traces to source text)."""
    case_id = await _indexed_case_id()
    if case_id is None:
        pytest.skip("Case not processed")

    async with SessionLocal() as session:
        draft = await generate_draft(
            case_id=case_id, draft_type=DraftType.title_review_summary, session=session
        )

    judgments = next(
        s for s in draft.content["sections"] if s["id"] == "judgments"
    )
    body = (judgments.get("body") or "").lower()
    blocks = judgments.get("blocks") or []

    # Pass condition: NO fabrication. Acceptable shapes:
    #   1. Section abstained outright.
    #   2. Body acknowledges absence ("no..."/"not...").
    #   3. Every block has at least one citation with a SourceSpan — the
    #      deterministic grounding guarantee.
    allowed = (
        judgments.get("abstained") is True
        or "no " in body
        or "not " in body
        or (
            bool(blocks)
            and all(
                any(c.get("spans") for c in (block.get("citations") or []))
                for block in blocks
            )
        )
    )
    assert allowed, f"judgments section must not fabricate: {judgments}"


@pytestmark_llm
async def test_case_status_memo_cross_references_multiple_documents():
    case_id = await _indexed_case_id()
    if case_id is None:
        pytest.skip("Case not processed")

    async with SessionLocal() as session:
        draft = await generate_draft(
            case_id=case_id, draft_type=DraftType.case_status_memo, session=session
        )

    # Gather every filename that shows up in any citation.
    cited_files: set[str] = set()
    for section in draft.content["sections"]:
        for block in section.get("blocks") or []:
            for cit in block.get("citations") or []:
                for sp in cit.get("spans") or []:
                    cited_files.add(sp.get("file", ""))

    # Must pull from at least court_order.txt AND servicer_email.txt AND title_search.
    assert any("court_order" in f for f in cited_files), cited_files
    assert any("servicer_email" in f for f in cited_files), cited_files
    assert any("title_search" in f for f in cited_files), cited_files


def test_renderer_produces_markdown_with_inline_citations():
    from datetime import datetime

    case = Case(
        id=1,
        case_number="2025-FC-08891",
        borrower="Rodriguez, Carlos A.",
        property_address="15201 SW 88th Ave",
        county="Miami-Dade",
        state="FL",
        servicer=None,
        loan_number=None,
        current_status=None,
        notes=None,
        context={},
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    from app.models.draft import DraftContent, DraftSection

    content = DraftContent(
        header={"effective_date": "2026-02-28"},
        sections=[
            DraftSection(
                id="liens",
                heading="Liens and Encumbrances",
                blocks=[
                    DraftBlock(
                        title="First Mortgage — Wells Fargo",
                        fields=[FieldLine(key="Amount", value="$445,000.00")],
                        badges=["ASSIGNED"],
                        citations=[
                            Citation(
                                claim="$445,000 Wells Fargo mortgage",
                                spans=[
                                    SourceSpan(
                                        file="title_search_page1.txt",
                                        line_start=16,
                                        line_end=19,
                                        raw_text="Mortgage...",
                                    )
                                ],
                            )
                        ],
                    )
                ],
            )
        ],
    )
    md = render_draft_markdown(content, DraftType.title_review_summary, case)
    assert "# Title Review Summary" in md
    assert "Rodriguez" in md
    assert "## Liens and Encumbrances" in md
    assert "ASSIGNED" in md
    assert "title_search_page1.txt:L16-19" in md

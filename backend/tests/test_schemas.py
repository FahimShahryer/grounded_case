"""Step 2 smoke tests — verify Pydantic schemas round-trip cleanly."""

from datetime import date
from decimal import Decimal

from app.models.common import SourceSpan
from app.models.draft import Citation, DraftBlock, DraftContent, DraftSection, FieldLine
from app.models.edit import StructuredDiff
from app.models.enums import DocType, DraftType, LienStatus, LienType
from app.models.extraction import (
    ActionItem,
    LienExtraction,
    TitleSearchExtraction,
)


def test_source_span_roundtrip():
    span = SourceSpan(
        file="title_search_page1.txt",
        line_start=16,
        line_end=19,
        raw_text="Mortgage from CARLOS A. RODRIGUEZ to WELLS FARGO",
    )
    data = span.model_dump()
    restored = SourceSpan.model_validate(data)
    assert restored == span
    assert restored.confidence == 1.0


def test_lien_extraction_nested_value_objects():
    lien = LienExtraction(
        lien_type=LienType.mortgage,
        creditor="Wells Fargo Bank, N.A.",
        amount=Decimal("445000.00"),
        date_recorded=date(2021, 2, 15),
        instrument_number="2021-0123456",
        status=LienStatus.assigned,
        source_spans=[
            SourceSpan(file="title_search_page1.txt", line_start=16, line_end=19, raw_text="..."),
        ],
    )
    dumped = lien.model_dump(mode="json")
    restored = LienExtraction.model_validate(dumped)
    assert restored.amount == Decimal("445000.00")
    assert restored.source_spans[0].line_start == 16


def test_title_search_envelope():
    env = TitleSearchExtraction(
        file_number="CLT-2025-08891",
        effective_date=date(2026, 2, 28),
        liens=[
            LienExtraction(lien_type=LienType.mortgage, creditor="Wells Fargo"),
            LienExtraction(lien_type=LienType.hoa_lis_pendens, creditor="Palmetto Bay HOA"),
        ],
    )
    dumped = env.model_dump(mode="json")
    assert len(dumped["liens"]) == 2
    assert dumped["liens"][0]["lien_type"] == "mortgage"


def test_draft_content_roundtrip():
    content = DraftContent(
        header={"case_number": "2025-FC-08891"},
        sections=[
            DraftSection(
                id="liens",
                heading="Liens and Encumbrances",
                blocks=[
                    DraftBlock(
                        title="First Mortgage — Wells Fargo",
                        fields=[FieldLine(key="amount", value="$445,000.00")],
                        badges=["ASSIGNED"],
                        citations=[
                            Citation(
                                claim="Original amount $445,000.00",
                                spans=[
                                    SourceSpan(
                                        file="title_search_page1.txt",
                                        line_start=16,
                                        line_end=19,
                                        raw_text="...",
                                    )
                                ],
                            )
                        ],
                    )
                ],
            )
        ],
    )
    dumped = content.model_dump(mode="json")
    restored = DraftContent.model_validate(dumped)
    assert restored.sections[0].blocks[0].badges == ["ASSIGNED"]
    assert restored.sections[0].blocks[0].fields[0].key == "amount"
    assert restored.sections[0].blocks[0].citations[0].spans[0].file == "title_search_page1.txt"


def test_structured_diff_default_empty():
    d = StructuredDiff()
    assert d.section_changes == []
    assert d.field_changes == []


def test_action_item_priority_default():
    a = ActionItem(description="File case management report")
    assert a.priority.value == "normal"


def test_enums_stringy():
    assert DocType.title_search == "title_search"
    assert DraftType.title_review_summary == "title_review_summary"

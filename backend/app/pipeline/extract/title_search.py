"""Extractor for title-search documents (Schedule B, legal descriptions)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.common import BookPage, SourceSpan
from app.models.enums import LienStatus, LienType
from app.models.extraction import (
    LienExtraction,
    OwnershipRecord,
    TaxStatus,
    TitleSearchExtraction,
)
from app.pipeline.extract.base import (
    ExtractorResult,
    parse_date,
    parse_decimal,
    run_extractor,
)

EXTRACTOR_TYPE = "title_search"
EXTRACTOR_VERSION = "v1"


# --------------------- LLM-facing schemas (strings, not Decimals/dates) ---


class LienLLM(BaseModel):
    lien_type: LienType
    creditor: str | None = Field(default=None, description="The entity holding the lien.")
    debtor: str | None = None
    amount_usd: str | None = Field(
        default=None,
        description="Amount as plain digits, no currency, e.g. '445000.00'. "
        "Fix OCR noise before outputting.",
    )
    date_recorded: str | None = Field(
        default=None, description="ISO date YYYY-MM-DD"
    )
    date_dated: str | None = Field(default=None, description="ISO date YYYY-MM-DD")
    instrument_number: str | None = Field(
        default=None, description="Like '2021-0123456'; fix OCR noise before outputting."
    )
    book: str | None = Field(default=None, description="O.R. Book reference, if present")
    page: str | None = Field(default=None, description="O.R. Page reference, if present")
    status: LienStatus = LienStatus.unknown
    notes: str | None = None
    source_spans: list[SourceSpan] = Field(default_factory=list)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class OwnershipLLM(BaseModel):
    grantor: str | None = None
    grantee: str
    instrument: str | None = Field(
        default=None, description="e.g. 'warranty deed', 'quitclaim'"
    )
    date_recorded: str | None = Field(default=None, description="ISO date YYYY-MM-DD")
    instrument_number: str | None = None
    source_spans: list[SourceSpan] = Field(default_factory=list)


class TaxLLM(BaseModel):
    year: int | None = None
    amount_usd: str | None = None
    paid: bool | None = None
    due_date: str | None = Field(default=None, description="ISO date YYYY-MM-DD")
    parcel_number: str | None = None
    notes: str | None = None
    source_spans: list[SourceSpan] = Field(default_factory=list)


class TitleSearchLLM(BaseModel):
    file_number: str | None = None
    effective_date: str | None = Field(
        default=None, description="ISO date YYYY-MM-DD"
    )
    property_address: str | None = None
    legal_description: str | None = None
    liens: list[LienLLM] = Field(default_factory=list)
    chain_of_title: list[OwnershipLLM] = Field(default_factory=list)
    tax_statuses: list[TaxLLM] = Field(default_factory=list)
    other_notes: list[str] = Field(default_factory=list)


# --------------------- System prompt -------------------------------------


_SYSTEM_PROMPT = """You extract structured data from title-search documents.

You will receive the text of one document with every line prefixed by
`[L{n}]`. The text often contains OCR artifacts:
  - `1` may represent `l` or `I` (e.g., `T1TLE` → `TITLE`, `Pa1metto` → `Palmetto`)
  - `O` may represent `0` (e.g., `$445,OOO.OO` → `$445,000.00`)
  - `0` may represent `O` in uppercase words
Output the INTENDED, CORRECTED values — do not preserve OCR noise in fields.

For EVERY extracted fact, include `source_spans` with:
  - `file`: the filename from the user message
  - `line_start` and `line_end`: the 1-based line numbers from the `[L#]` prefixes
  - `raw_text`: the verbatim slice of the source (OCR noise preserved here)
  - `confidence`: 0.0-1.0

Extract:
  - Every lien / encumbrance (mortgage, assignment, HOA lis pendens, tax lien,
    judgment, easement, restrictive covenant). Populate:
    lien_type, creditor, amount_usd, date_recorded, date_dated, instrument_number,
    book/page if given, status.
  - Chain of ownership (conveyances, warranty deeds, quitclaims).
  - Tax statuses per year (amount, paid/unpaid, parcel_number).
  - File number, effective date, property address, legal description.

Rules:
  - If a field isn't clearly stated in the document, leave it null.
  - Do not invent facts. Do not copy between unrelated paragraphs.
  - Status values: mortgages assigned to another party are "assigned";
    lis pendens and active liens are "active"; satisfied prior mortgages are
    "satisfied".
"""


# --------------------- Converter → canonical typed schema -----------------


def _to_canonical(llm_obj: TitleSearchLLM) -> TitleSearchExtraction:
    return TitleSearchExtraction(
        file_number=llm_obj.file_number,
        effective_date=parse_date(llm_obj.effective_date),
        property_address=llm_obj.property_address,
        legal_description=llm_obj.legal_description,
        liens=[
            LienExtraction(
                lien_type=lien.lien_type,
                creditor=lien.creditor,
                debtor=lien.debtor,
                amount=parse_decimal(lien.amount_usd),
                date_recorded=parse_date(lien.date_recorded),
                date_dated=parse_date(lien.date_dated),
                instrument_number=lien.instrument_number,
                book_page=(
                    BookPage(book=lien.book, page=lien.page)
                    if (lien.book and lien.page)
                    else None
                ),
                status=lien.status,
                notes=lien.notes,
                source_spans=lien.source_spans,
                confidence=lien.confidence,
            )
            for lien in llm_obj.liens
        ],
        chain_of_title=[
            OwnershipRecord(
                grantor=o.grantor,
                grantee=o.grantee,
                instrument=o.instrument,
                date_recorded=parse_date(o.date_recorded),
                instrument_number=o.instrument_number,
                source_spans=o.source_spans,
            )
            for o in llm_obj.chain_of_title
        ],
        tax_statuses=[
            TaxStatus(
                year=t.year,
                amount=parse_decimal(t.amount_usd),
                paid=t.paid,
                due_date=parse_date(t.due_date),
                parcel_number=t.parcel_number,
                notes=t.notes,
                source_spans=t.source_spans,
            )
            for t in llm_obj.tax_statuses
        ],
        other_notes=llm_obj.other_notes,
    )


# --------------------- Public entrypoint ---------------------------------


async def extract_title_search(
    *, text: str, filename: str, case_id: int | None = None
) -> ExtractorResult:
    llm_obj = await run_extractor(
        system_prompt=_SYSTEM_PROMPT,
        text=text,
        filename=filename,
        response_model=TitleSearchLLM,
        case_id=case_id,
    )
    canonical = _to_canonical(llm_obj)  # type: ignore[arg-type]
    return ExtractorResult(
        extractor_type=EXTRACTOR_TYPE,
        extractor_version=EXTRACTOR_VERSION,
        payload=canonical.model_dump(mode="json"),
    )

"""Extractor for court orders (case management, scheduling, etc.)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.common import SourceSpan
from app.models.enums import Priority
from app.models.extraction import (
    ActionItem,
    CourtOrderExtraction,
    Deadline,
)
from app.pipeline.extract.base import (
    ExtractorResult,
    parse_date,
    run_extractor,
)

EXTRACTOR_TYPE = "court_order"
EXTRACTOR_VERSION = "v1"


# --------------------- LLM-facing schemas --------------------------------


class DeadlineLLM(BaseModel):
    description: str
    due_date: str = Field(description="ISO date YYYY-MM-DD")
    required_action: str | None = None
    source_spans: list[SourceSpan] = Field(default_factory=list)


class RequirementLLM(BaseModel):
    description: str
    priority: Priority = Priority.high
    deadline: str | None = Field(default=None, description="ISO date YYYY-MM-DD")
    owner: str | None = None
    source_spans: list[SourceSpan] = Field(default_factory=list)


class CourtOrderLLM(BaseModel):
    court: str | None = None
    case_number: str | None = None
    judge: str | None = None
    deadlines: list[DeadlineLLM] = Field(default_factory=list)
    required_appearances: list[RequirementLLM] = Field(default_factory=list)
    filing_requirements: list[RequirementLLM] = Field(default_factory=list)
    other_notes: list[str] = Field(default_factory=list)


# --------------------- System prompt -------------------------------------


_SYSTEM_PROMPT = """You extract structured data from a court order.

You will receive the text with every line prefixed by `[L{n}]`.
Court orders contain formal legal language; dates and filing requirements
are often stated precisely. Your job is to capture all operational details
so counsel does not miss a deadline.

The text may contain OCR artifacts from scanned documents:
  - `1` may represent `l` or `I` (e.g., `F1orida` → `Florida`, `P1aintiff` → `Plaintiff`)
  - `O` may represent `0` in numeric contexts (case numbers, docket IDs, dates)
  - `0` may represent `O` inside uppercase words
Output the INTENDED, CORRECTED values in structured fields — do not
preserve OCR noise in field values. Preserve the verbatim noisy text
only in `source_spans.raw_text` (for audit).

For every extracted fact, include a `source_spans` list with:
  - `file`: the filename
  - `line_start` and `line_end`: the 1-based line numbers from the `[L#]` prefixes
  - `raw_text`: the verbatim slice of the source (OCR noise preserved here)
  - `confidence`: 0.0-1.0

Extract:
  - court: the court's name and division
  - case_number: the case docket number
  - judge: the presiding judge
  - deadlines: every date something is due. For each:
      description, due_date (ISO), required_action (what must happen by then).
  - required_appearances: hearings/conferences that require someone to appear.
  - filing_requirements: specific documents required to be filed.

Rules:
  - One deadline per item. If multiple deadlines are listed in a numbered list,
    split them.
  - Never invent dates. If a relative date ("10 days before the conference")
    can be computed from a stated absolute date, compute it; otherwise leave null.
  - Priority: appearances are typically "high"; filing deadlines are "high";
    compliance reports are "normal".
"""


# --------------------- Converter → canonical typed schema -----------------


def _to_canonical(obj: CourtOrderLLM) -> CourtOrderExtraction:
    return CourtOrderExtraction(
        court=obj.court,
        case_number=obj.case_number,
        judge=obj.judge,
        deadlines=[
            Deadline(
                description=d.description,
                due_date=parse_date(d.due_date) or _fallback_date(d.due_date),
                required_action=d.required_action,
                source_spans=d.source_spans,
            )
            for d in obj.deadlines
            if parse_date(d.due_date) is not None
        ],
        required_appearances=[
            ActionItem(
                description=r.description,
                priority=r.priority,
                deadline=parse_date(r.deadline),
                owner=r.owner,
                source_spans=r.source_spans,
            )
            for r in obj.required_appearances
        ],
        filing_requirements=[
            ActionItem(
                description=r.description,
                priority=r.priority,
                deadline=parse_date(r.deadline),
                owner=r.owner,
                source_spans=r.source_spans,
            )
            for r in obj.filing_requirements
        ],
        other_notes=obj.other_notes,
    )


def _fallback_date(s: str):
    """Defensive: if the LLM wrote a non-ISO date, try harder before dropping."""
    from datetime import date

    d = parse_date(s)
    return d if d else date(1900, 1, 1)  # placeholder sentinel (kept for type-safety)


async def extract_court_order(
    *, text: str, filename: str, case_id: int | None = None
) -> ExtractorResult:
    llm_obj = await run_extractor(
        system_prompt=_SYSTEM_PROMPT,
        text=text,
        filename=filename,
        response_model=CourtOrderLLM,
        case_id=case_id,
    )
    canonical = _to_canonical(llm_obj)  # type: ignore[arg-type]
    return ExtractorResult(
        extractor_type=EXTRACTOR_TYPE,
        extractor_version=EXTRACTOR_VERSION,
        payload=canonical.model_dump(mode="json"),
    )

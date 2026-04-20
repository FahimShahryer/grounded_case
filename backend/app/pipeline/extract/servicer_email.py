"""Extractor for loan-servicer emails."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.common import SourceSpan
from app.models.enums import Priority
from app.models.extraction import (
    ActionItem,
    AttorneyInfo,
    PayoffUpdate,
    ServicerEmailExtraction,
    TransferInfo,
)
from app.pipeline.extract.base import (
    ExtractorResult,
    parse_date,
    parse_decimal,
    run_extractor,
)

EXTRACTOR_TYPE = "servicer_email"
EXTRACTOR_VERSION = "v1"


# --------------------- LLM-facing schemas --------------------------------


class ActionItemLLM(BaseModel):
    description: str
    priority: Priority = Priority.normal
    deadline: str | None = Field(default=None, description="ISO date YYYY-MM-DD")
    owner: str | None = None
    source_spans: list[SourceSpan] = Field(default_factory=list)


class PayoffLLM(BaseModel):
    amount_usd: str = Field(description="Plain digits, no currency.")
    as_of: str | None = Field(default=None, description="ISO date YYYY-MM-DD")
    source_spans: list[SourceSpan] = Field(default_factory=list)


class TransferLLM(BaseModel):
    from_servicer: str | None = None
    to_servicer: str | None = None
    effective_date: str | None = Field(default=None, description="ISO date YYYY-MM-DD")
    notes: str | None = None
    source_spans: list[SourceSpan] = Field(default_factory=list)


class AttorneyLLM(BaseModel):
    name: str
    firm: str | None = None
    phone: str | None = None
    represents: str | None = None
    source_spans: list[SourceSpan] = Field(default_factory=list)


class ServicerEmailLLM(BaseModel):
    sender: str | None = None
    received_date: str | None = Field(default=None, description="ISO date YYYY-MM-DD")
    action_items: list[ActionItemLLM] = Field(default_factory=list)
    payoff_update: PayoffLLM | None = None
    transfer: TransferLLM | None = None
    attorney: AttorneyLLM | None = None
    other_notes: list[str] = Field(default_factory=list)


# --------------------- System prompt -------------------------------------


_SYSTEM_PROMPT = """You extract structured data from a loan-servicer email.

You will receive the text with every line prefixed by `[L{n}]`.
The email mixes formal instructions with casual prose; there may be
multiple action items buried in a single paragraph.

The text may contain OCR artifacts (the email body might be a scanned
forward or screenshot):
  - `1` may represent `l` or `I` (e.g., `Wel1s Fargo` → `Wells Fargo`)
  - `O` may represent `0` (e.g., `$487,92O.OO` → `$487,920.00`, `2O21-O123456` → `2021-0123456`)
  - `0` may represent `O` inside uppercase words
Output the INTENDED, CORRECTED values in structured fields — do not
preserve OCR noise in field values. Preserve the verbatim noisy text
only in `source_spans.raw_text` (for audit).

For every extracted fact, include a `source_spans` list with:
  - `file`: the filename
  - `line_start` and `line_end`: the 1-based line numbers from the `[L#]` prefixes
  - `raw_text`: the exact verbatim slice of the source (OCR noise preserved here)
  - `confidence`: 0.0-1.0

Extract:
  - sender: email sender name (if present)
  - received_date: when the email was sent
  - action_items: every distinct task the servicer is asking to be done.
      One action item per task. Preserve priority the servicer emphasizes
      (words like "URGENT", "please", deadlines) — priority values:
      urgent | high | normal | low.
  - payoff_update: if the email states a payoff amount, extract it.
  - transfer: if the email mentions a servicing transfer (from whom, to whom,
      effective when).
  - attorney: if the borrower has retained counsel, capture their name,
      firm, phone (from anywhere in the email body).

Rules:
  - Do not invent data. If the email does not say it, leave it null.
  - One action per action_items entry. If a single sentence contains two
    tasks, split them.
  - Amounts are plain digits (e.g. "487920.00"), not "$487,920".
"""


# --------------------- Converter → canonical typed schema -----------------


def _to_canonical(obj: ServicerEmailLLM) -> ServicerEmailExtraction:
    return ServicerEmailExtraction(
        sender=obj.sender,
        received_date=parse_date(obj.received_date),
        action_items=[
            ActionItem(
                description=a.description,
                priority=a.priority,
                deadline=parse_date(a.deadline),
                owner=a.owner,
                source_spans=a.source_spans,
            )
            for a in obj.action_items
        ],
        payoff_update=(
            PayoffUpdate(
                amount=parse_decimal(obj.payoff_update.amount_usd) or 0,
                as_of=parse_date(obj.payoff_update.as_of),
                source_spans=obj.payoff_update.source_spans,
            )
            if obj.payoff_update
            else None
        ),
        transfer=(
            TransferInfo(
                from_servicer=obj.transfer.from_servicer,
                to_servicer=obj.transfer.to_servicer,
                effective_date=parse_date(obj.transfer.effective_date),
                notes=obj.transfer.notes,
                source_spans=obj.transfer.source_spans,
            )
            if obj.transfer
            else None
        ),
        attorney=(
            AttorneyInfo(
                name=obj.attorney.name,
                firm=obj.attorney.firm,
                phone=obj.attorney.phone,
                represents=obj.attorney.represents,
                source_spans=obj.attorney.source_spans,
            )
            if obj.attorney
            else None
        ),
        other_notes=obj.other_notes,
    )


async def extract_servicer_email(
    *, text: str, filename: str, case_id: int | None = None
) -> ExtractorResult:
    llm_obj = await run_extractor(
        system_prompt=_SYSTEM_PROMPT,
        text=text,
        filename=filename,
        response_model=ServicerEmailLLM,
        case_id=case_id,
    )
    canonical = _to_canonical(llm_obj)  # type: ignore[arg-type]
    return ExtractorResult(
        extractor_type=EXTRACTOR_TYPE,
        extractor_version=EXTRACTOR_VERSION,
        payload=canonical.model_dump(mode="json"),
    )

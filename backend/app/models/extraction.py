"""Schemas for per-document extraction results.

Every per-doc-type extractor (Step 4) returns one of these.
The payload is stored as JSONB on the `extractions` table, so the
schema can evolve without migrations.
"""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.common import BookPage, SourceSpan
from app.models.enums import LienStatus, LienType, Priority


class LienExtraction(BaseModel):
    lien_type: LienType
    creditor: str | None = None
    debtor: str | None = None
    amount: Decimal | None = None
    date_recorded: date | None = None
    date_dated: date | None = None
    instrument_number: str | None = None
    book_page: BookPage | None = None
    lien_position: int | None = None
    status: LienStatus = LienStatus.unknown
    notes: str | None = None
    source_spans: list[SourceSpan] = Field(default_factory=list)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class OwnershipRecord(BaseModel):
    grantor: str | None = None
    grantee: str
    instrument: str | None = None  # "warranty deed", "quitclaim"
    date_recorded: date | None = None
    instrument_number: str | None = None
    source_spans: list[SourceSpan] = Field(default_factory=list)


class TaxStatus(BaseModel):
    year: int | None = None
    amount: Decimal | None = None
    paid: bool | None = None
    due_date: date | None = None
    parcel_number: str | None = None
    notes: str | None = None
    source_spans: list[SourceSpan] = Field(default_factory=list)


class ActionItem(BaseModel):
    description: str
    priority: Priority = Priority.normal
    deadline: date | None = None
    owner: str | None = None
    source_spans: list[SourceSpan] = Field(default_factory=list)


class Deadline(BaseModel):
    description: str
    due_date: date
    required_action: str | None = None
    source_spans: list[SourceSpan] = Field(default_factory=list)


class TransferInfo(BaseModel):
    from_servicer: str | None = None
    to_servicer: str | None = None
    effective_date: date | None = None
    notes: str | None = None
    source_spans: list[SourceSpan] = Field(default_factory=list)


class PayoffUpdate(BaseModel):
    amount: Decimal
    as_of: date | None = None
    source_spans: list[SourceSpan] = Field(default_factory=list)


class AttorneyInfo(BaseModel):
    name: str
    firm: str | None = None
    phone: str | None = None
    represents: str | None = None
    source_spans: list[SourceSpan] = Field(default_factory=list)


# -------- Per-document-type extraction envelopes --------


class TitleSearchExtraction(BaseModel):
    file_number: str | None = None
    effective_date: date | None = None
    property_address: str | None = None
    legal_description: str | None = None
    liens: list[LienExtraction] = Field(default_factory=list)
    chain_of_title: list[OwnershipRecord] = Field(default_factory=list)
    tax_statuses: list[TaxStatus] = Field(default_factory=list)
    other_notes: list[str] = Field(default_factory=list)


class ServicerEmailExtraction(BaseModel):
    sender: str | None = None
    received_date: date | None = None
    action_items: list[ActionItem] = Field(default_factory=list)
    payoff_update: PayoffUpdate | None = None
    transfer: TransferInfo | None = None
    attorney: AttorneyInfo | None = None
    other_notes: list[str] = Field(default_factory=list)


class CourtOrderExtraction(BaseModel):
    court: str | None = None
    case_number: str | None = None
    judge: str | None = None
    deadlines: list[Deadline] = Field(default_factory=list)
    required_appearances: list[ActionItem] = Field(default_factory=list)
    filing_requirements: list[ActionItem] = Field(default_factory=list)
    other_notes: list[str] = Field(default_factory=list)


class ExtractionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int
    extractor_type: str
    extractor_version: str
    payload: dict
    confidence: float
    human_verified: bool
    created_at: datetime

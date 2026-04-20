"""Value objects embedded inside structured facts and drafts.

These are NOT rows — they get stored as JSONB on their parent row.
"""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class SourceSpan(BaseModel):
    """A pointer back to a span of source text that supports a claim.

    Every extracted fact and every citation carries at least one of these.
    """

    model_config = ConfigDict(frozen=True)

    file: str = Field(description="Filename relative to the case's document store.")
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    raw_text: str = Field(description="The exact text at the cited span.")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class Money(BaseModel):
    """Typed money amount. Parsed from strings; rejects OCR-garbled inputs."""

    model_config = ConfigDict(frozen=True)

    amount: Decimal
    currency: str = "USD"


class BookPage(BaseModel):
    """Official-records book/page reference (e.g., 'O.R. Book 18924, Page 445')."""

    model_config = ConfigDict(frozen=True)

    book: str
    page: str

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class CaseCreate(BaseModel):
    case_number: str
    borrower: str
    property_address: str
    county: str | None = None
    state: str | None = None
    servicer: str | None = None
    loan_number: str | None = None
    loan_amount: Decimal | None = None
    loan_date: date | None = None
    default_date: date | None = None
    current_status: str | None = None
    notes: str | None = None
    context: dict = Field(default_factory=dict, description="Full case_context.json payload.")


class CaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    case_number: str
    borrower: str
    property_address: str
    county: str | None
    state: str | None
    servicer: str | None
    current_status: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime

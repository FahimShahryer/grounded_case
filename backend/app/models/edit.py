"""Structured edit schemas.

An edit is a structured diff between a system-generated draft and the
operator-edited version. Stored as JSONB; later mined into patterns.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.draft import DraftContent
from app.models.enums import EditChangeKind


class SectionChange(BaseModel):
    op: Literal["add", "remove", "rename", "reorder", "modify"]
    section_id: str
    before: dict | None = None
    after: dict | None = None
    kind: EditChangeKind = EditChangeKind.rule
    reason: str | None = None


class FieldChange(BaseModel):
    section_id: str
    block_index: int | None = None
    field: str
    op: Literal["add", "remove", "edit"]
    before: str | None = None
    after: str | None = None
    kind: EditChangeKind = EditChangeKind.rule


class StructuredDiff(BaseModel):
    section_changes: list[SectionChange] = Field(default_factory=list)
    field_changes: list[FieldChange] = Field(default_factory=list)


class EditCreate(BaseModel):
    operator_id: str | None = None
    operator_version: DraftContent
    rationale: str | None = None


class EditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    draft_id: int
    operator_id: str | None
    operator_version: DraftContent
    structured_diff: StructuredDiff
    rationale: str | None
    created_at: datetime

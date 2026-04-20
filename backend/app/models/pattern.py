"""Learned patterns and the templates that reference them.

Patterns are mined from operator edits and expressed as small rules
with scope, condition, and assertion.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import DraftType, PatternScope


class Pattern(BaseModel):
    """A single learned rule mined from one or more edits."""

    scope: PatternScope = PatternScope.firm
    draft_type: DraftType | None = None  # None = applies to any draft type
    section_id: str | None = None
    rule_when: str  # "draft_type=title_review AND section=liens"
    rule_must: str  # "include instrument_number for each lien"
    confidence: float = Field(ge=0.0, le=1.0)


class PatternOut(Pattern):
    model_config = ConfigDict(from_attributes=True)

    id: int
    supporting_edit_ids: list[int] = Field(default_factory=list)
    version: int
    active: bool
    created_at: datetime
    updated_at: datetime


class TemplateManifest(BaseModel):
    """Typed structure of a template — what sections to produce and in what order."""

    sections: list[dict] = Field(default_factory=list)
    pattern_refs: list[int] = Field(default_factory=list)


class TemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    draft_type: DraftType
    version: int
    manifest: TemplateManifest
    active: bool
    created_at: datetime

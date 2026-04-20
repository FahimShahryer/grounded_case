"""Draft schemas.

Drafts are generated outputs (Title Review Summary, Case Status Memo, etc.).
The structured content lives in JSONB; a rendered markdown version is also
persisted for easy display.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.common import SourceSpan
from app.models.enums import DraftType


class Citation(BaseModel):
    """Inline citation linking a claim to evidence."""

    claim: str = Field(description="The claim text that the citation supports.")
    spans: list[SourceSpan] = Field(default_factory=list)


class FieldLine(BaseModel):
    """One key/value row inside a DraftBlock.

    Why a list of rows instead of a dict: OpenAI's strict JSON-schema mode
    disallows free-form `additionalProperties`, which a Python dict requires.
    The list-of-pairs shape stays compatible AND preserves operator-intended
    ordering (which dicts don't guarantee across serialization boundaries).
    """

    key: str
    value: str


class DraftBlock(BaseModel):
    """A structured block inside a draft section (e.g., one lien entry)."""

    title: str | None = None
    fields: list[FieldLine] = Field(default_factory=list)
    badges: list[str] = Field(default_factory=list)  # e.g. "ASSIGNED", "ACTION REQUIRED"
    notes: str | None = None
    action_items: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)


class DraftSection(BaseModel):
    id: str  # e.g. "liens_and_encumbrances"
    heading: str
    body: str | None = None  # free prose, optional
    blocks: list[DraftBlock] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    abstained: bool = False  # True if no evidence was found for this section


class DraftContent(BaseModel):
    """The structured draft object — serialized to JSONB on the drafts table."""

    header: dict[str, str] = Field(default_factory=dict)
    sections: list[DraftSection] = Field(default_factory=list)


class DraftOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    case_id: int
    draft_type: DraftType
    template_version: int
    model: str
    content: DraftContent
    content_markdown: str
    parent_draft_id: int | None
    created_at: datetime

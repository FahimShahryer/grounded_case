"""Canonical, deduplicated facts that exist at the case level.

A fact has many pieces of evidence (source spans across multiple documents).
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.common import SourceSpan


class FactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    case_id: int
    fact_type: str  # "lien", "action_item", "deadline", ...
    dedup_key: str
    payload: dict
    confidence: float
    valid_from: date | None = None
    valid_to: date | None = None
    created_at: datetime
    updated_at: datetime


class FactEvidenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    fact_id: int
    document_id: int
    span: SourceSpan
    created_at: datetime


class FactConflict(BaseModel):
    """A canonical fact where two sources disagreed on a material field."""

    dedup_key: str
    fact_type: str
    candidates: list[dict] = Field(default_factory=list)


# --------- LLM-facing schemas for the semantic resolver --------------------


FactType = Literal[
    "lien",
    "tax",
    "ownership",
    "payoff",
    "transfer",
    "attorney",
    "action_item",
    "deadline",
    "appearance",
    "filing_requirement",
]


class EvidenceRefLLM(BaseModel):
    """One pointer back to a specific piece of source text that supports a fact.

    `document_id` must be one of the document IDs supplied in the resolver's
    user message. `line_start`/`line_end` / `raw_text` come straight from the
    extractor's `source_spans` — copy them verbatim.
    """

    document_id: int = Field(description="id of the document this evidence came from")
    line_start: int
    line_end: int
    raw_text: str = Field(description="verbatim slice from the source document")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class CanonicalFactLLM(BaseModel):
    """One canonical, deduplicated fact about the case.

    The LLM produces these by merging per-document extractions. One
    CanonicalFactLLM may be backed by evidence from multiple documents —
    that's exactly the dedup the resolver exists to perform.
    """

    fact_type: FactType
    dedup_hint: str = Field(
        description=(
            "Short human-readable identifier for this fact, used only for "
            "stable deduplication across re-runs. E.g. 'mortgage-wells-fargo-445k', "
            "'deadline-2026-04-15-proof-of-service'."
        )
    )
    payload_json: str = Field(
        description=(
            "Canonical merged fact data, encoded as a compact JSON object "
            "string. E.g. '{\"lien_type\":\"mortgage\",\"creditor\":\"Wells "
            "Fargo\",\"amount\":\"445000\",\"date_recorded\":\"2021-02-08\"}'. "
            "Keys depend on fact_type — mirror the shape of the source "
            "extraction's equivalent field. Do NOT include source_spans here."
        )
    )
    evidence: list[EvidenceRefLLM] = Field(
        default_factory=list,
        description=(
            "Every document + source span that supports this fact. Must have "
            "at least one entry. If two documents independently mention the "
            "same fact, both are listed here."
        ),
    )
    conflict: bool = Field(
        default=False,
        description=(
            "True iff two sources agreed this is the same fact but disagreed "
            "on a material value (e.g. two different payoff amounts)."
        ),
    )
    conflict_note: str | None = Field(
        default=None,
        description="One sentence explaining the conflict if conflict=true.",
    )


class ResolverOutput(BaseModel):
    facts: list[CanonicalFactLLM]

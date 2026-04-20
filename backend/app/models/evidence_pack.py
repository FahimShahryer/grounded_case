"""Evidence Pack — structured input for grounded draft generation.

An EvidencePack is what the section-by-section generator receives. It
carries:
  - `structured_facts`: canonical facts pulled from the case knowledge graph
  - `text_evidence`: ranked text chunks retrieved + reranked for this section
  - `known_gaps`: explicit statements of absence (e.g. "no judgments found")
  - `conflicts`: resolver-detected disagreements so the generator can hedge
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.models.common import SourceSpan
from app.models.fact import FactConflict


class EvidenceChunk(BaseModel):
    """One retrieved text chunk — with ranks + citation metadata."""

    model_config = ConfigDict(frozen=True)

    chunk_id: int
    document_id: int
    filename: str
    doc_type: str
    line_start: int | None
    line_end: int | None
    section_header: str | None
    text: str
    score: float = Field(description="Fused score (RRF or reranker).")
    ranks: dict[str, int] = Field(default_factory=dict)


class EvidenceFact(BaseModel):
    """A canonical fact + its source spans across documents."""

    model_config = ConfigDict(frozen=True)

    fact_id: int
    fact_type: str
    dedup_key: str
    payload: dict
    confidence: float
    evidence_spans: list[SourceSpan] = Field(default_factory=list)


class EvidencePack(BaseModel):
    """Everything a draft section needs to stay grounded."""

    model_config = ConfigDict(frozen=True)

    section_id: str
    description: str
    structured_facts: list[EvidenceFact] = Field(default_factory=list)
    text_evidence: list[EvidenceChunk] = Field(default_factory=list)
    known_gaps: list[str] = Field(default_factory=list)
    conflicts: list[FactConflict] = Field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.structured_facts and not self.text_evidence

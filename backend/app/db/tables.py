"""SQLAlchemy 2.0 typed ORM tables.

All tables import from `app.db.base.Base` so Alembic's autogenerate can
read a single `Base.metadata`.

Design choices:
- Integer primary keys (simpler for dev; swap to UUID in production).
- JSONB for flexible payloads (extractions, drafts, patterns) so the
  *shape* can evolve without migrations; queryable columns are lifted
  out as proper typed columns.
- TIMESTAMPTZ for every timestamp.
- pgvector `Vector(1536)` on chunks.embedding with an HNSW index
  created in the initial migration (not declared here, since index
  options live in raw SQL).
"""

from datetime import date, datetime
from decimal import Decimal

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

# ---------- Cases ----------


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_number: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    borrower: Mapped[str] = mapped_column(String(255))
    property_address: Mapped[str] = mapped_column(String(512))
    county: Mapped[str | None] = mapped_column(String(128))
    state: Mapped[str | None] = mapped_column(String(8))
    servicer: Mapped[str | None] = mapped_column(String(255))
    loan_number: Mapped[str | None] = mapped_column(String(64))
    loan_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    loan_date: Mapped[date | None] = mapped_column(Date)
    default_date: Mapped[date | None] = mapped_column(Date)
    current_status: Mapped[str | None] = mapped_column(String(64))
    notes: Mapped[str | None] = mapped_column(Text)
    context: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    documents: Mapped[list["Document"]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )


# ---------- Documents ----------


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    doc_type: Mapped[str] = mapped_column(String(32), index=True)
    raw_text: Mapped[str] = mapped_column(Text)
    cleaned_text: Mapped[str | None] = mapped_column(Text)
    content_sha256: Mapped[str] = mapped_column(String(64), index=True)
    # Canonical location of the original bytes in MinIO. Nullable so
    # legacy rows + test fixtures stay valid without a blob.
    storage_key: Mapped[str | None] = mapped_column(String(512))
    meta: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    case: Mapped[Case] = relationship(back_populates="documents")


# ---------- Extractions (per-document raw extractor output) ----------


class Extraction(Base):
    __tablename__ = "extractions"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    extractor_type: Mapped[str] = mapped_column(String(64), index=True)
    extractor_version: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSONB)
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), default=1.0)
    human_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ---------- Facts (canonical, deduplicated) ----------


class Fact(Base):
    __tablename__ = "facts"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"), index=True
    )
    fact_type: Mapped[str] = mapped_column(String(32), index=True)
    dedup_key: Mapped[str] = mapped_column(String(255), index=True)
    payload: Mapped[dict] = mapped_column(JSONB)
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), default=1.0)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class FactEvidence(Base):
    __tablename__ = "fact_evidence"

    id: Mapped[int] = mapped_column(primary_key=True)
    fact_id: Mapped[int] = mapped_column(
        ForeignKey("facts.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    span: Mapped[dict] = mapped_column(JSONB)  # SourceSpan value object
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ---------- Chunks (retrieval units with embeddings) ----------


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    line_start: Mapped[int | None] = mapped_column(Integer)
    line_end: Mapped[int | None] = mapped_column(Integer)
    section_header: Mapped[str | None] = mapped_column(String(255))
    doc_type: Mapped[str] = mapped_column(String(32), index=True)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ---------- Drafts ----------


class Draft(Base):
    __tablename__ = "drafts"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"), index=True
    )
    draft_type: Mapped[str] = mapped_column(String(64), index=True)
    template_id: Mapped[int | None] = mapped_column(
        ForeignKey("templates.id", ondelete="SET NULL")
    )
    template_version: Mapped[int] = mapped_column(Integer, default=1)
    model: Mapped[str] = mapped_column(String(64))
    content: Mapped[dict] = mapped_column(JSONB)  # DraftContent serialized
    content_markdown: Mapped[str] = mapped_column(Text)
    parent_draft_id: Mapped[int | None] = mapped_column(
        ForeignKey("drafts.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ---------- Edits ----------


class Edit(Base):
    __tablename__ = "edits"

    id: Mapped[int] = mapped_column(primary_key=True)
    draft_id: Mapped[int] = mapped_column(
        ForeignKey("drafts.id", ondelete="CASCADE"), index=True
    )
    operator_id: Mapped[str | None] = mapped_column(String(64), index=True)
    operator_version: Mapped[dict] = mapped_column(JSONB)
    structured_diff: Mapped[dict] = mapped_column(JSONB)
    rationale: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ---------- Patterns & Templates ----------


class Pattern(Base):
    __tablename__ = "patterns"

    id: Mapped[int] = mapped_column(primary_key=True)
    scope: Mapped[str] = mapped_column(String(32), index=True)
    draft_type: Mapped[str | None] = mapped_column(String(64), index=True)
    section_id: Mapped[str | None] = mapped_column(String(64))
    rule_when: Mapped[str] = mapped_column(Text)
    rule_must: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Numeric(4, 3))
    supporting_edit_ids: Mapped[list[int]] = mapped_column(ARRAY(Integer), default=list)
    version: Mapped[int] = mapped_column(Integer, default=1)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Template(Base):
    __tablename__ = "templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    draft_type: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[int] = mapped_column(Integer)
    manifest: Mapped[dict] = mapped_column(JSONB)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ---------- LLM Call Log (observability) ----------


class LlmCall(Base):
    __tablename__ = "llm_calls"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int | None] = mapped_column(
        ForeignKey("cases.id", ondelete="SET NULL"), index=True
    )
    purpose: Mapped[str] = mapped_column(String(32), index=True)
    model: Mapped[str] = mapped_column(String(64))
    prompt_hash: Mapped[str] = mapped_column(String(64), index=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

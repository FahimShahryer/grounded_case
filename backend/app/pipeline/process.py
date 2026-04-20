"""Orchestrator for the document pipeline.

Given a case, walk every attached document, run OCR repair + the
appropriate extractor, and then resolve facts across documents. Each
stage is idempotent: rerunning does not re-extract documents that are
already at the current `extractor_version`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.tables import Document, Extraction
from app.models.fact import FactConflict
from app.pipeline.extract import extract_document
from app.pipeline.extract.base import ExtractorResult
from app.pipeline.index import index_case
from app.pipeline.ocr_repair import repair_ocr
from app.pipeline.resolve import resolve_facts

_EXTRACTOR_VERSION = "v1"


@dataclass
class ProcessResult:
    case_id: int
    documents_total: int = 0
    documents_processed: int = 0  # ran OCR repair this run
    extractions_created: int = 0
    extractions_reused: int = 0
    facts_created: int = 0
    facts_reused: int = 0
    evidence_created: int = 0
    chunks_created: int = 0
    chunks_embedded: int = 0
    conflicts: list[FactConflict] = field(default_factory=list)


async def process_case(case_id: int, session: AsyncSession) -> ProcessResult:
    result = ProcessResult(case_id=case_id)

    docs = (
        (await session.execute(select(Document).where(Document.case_id == case_id)))
        .scalars()
        .all()
    )
    result.documents_total = len(docs)

    for doc in docs:
        # Step 1: OCR repair (idempotent — skip if already cleaned).
        if not doc.cleaned_text:
            cleaned, stats = repair_ocr(doc.raw_text)
            doc.cleaned_text = cleaned
            meta = dict(doc.meta or {})
            meta["ocr_repair"] = dict(stats)
            doc.meta = meta
            session.add(doc)
            await session.commit()
            result.documents_processed += 1

        # Step 2: Extraction (idempotent by extractor_version).
        existing_q = select(Extraction).where(
            Extraction.document_id == doc.id,
            Extraction.extractor_version == _EXTRACTOR_VERSION,
        )
        already = (await session.execute(existing_q)).scalar_one_or_none()
        if already is not None:
            result.extractions_reused += 1
            continue

        ex: ExtractorResult = await extract_document(
            doc_type=doc.doc_type,
            text=doc.cleaned_text or doc.raw_text,
            filename=doc.filename,
            case_id=case_id,
        )
        row = Extraction(
            document_id=doc.id,
            extractor_type=ex.extractor_type,
            extractor_version=ex.extractor_version,
            payload=ex.payload,
            confidence=ex.confidence,
        )
        session.add(row)
        await session.commit()
        result.extractions_created += 1

    # Step 3: Cross-document resolution.
    resolve_out = await resolve_facts(case_id, session)
    result.facts_created = resolve_out.facts_created
    result.facts_reused = resolve_out.facts_reused
    result.evidence_created = resolve_out.evidence_created
    result.conflicts = resolve_out.conflicts

    # Step 4: Indexing for retrieval.
    idx = await index_case(case_id, session)
    result.chunks_created = idx.chunks_created
    result.chunks_embedded = idx.chunks_embedded

    return result

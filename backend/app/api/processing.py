from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import SessionDep
from app.db.tables import Case, Document, Extraction, Fact, FactEvidence
from app.models.fact import FactConflict
from app.pipeline.process import process_case

router = APIRouter(prefix="/api/cases/{case_id}", tags=["processing"])


class ProcessResponse(BaseModel):
    case_id: int
    documents_total: int
    documents_processed: int
    extractions_created: int
    extractions_reused: int
    facts_created: int
    facts_reused: int
    evidence_created: int
    chunks_created: int
    chunks_embedded: int
    conflicts: list[FactConflict] = Field(default_factory=list)


class ExtractionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    document_id: int
    extractor_type: str
    extractor_version: str
    payload: dict
    confidence: float
    human_verified: bool
    created_at: datetime


class EvidenceItem(BaseModel):
    document_id: int
    document_filename: str
    span: dict


class FactResponse(BaseModel):
    id: int
    case_id: int
    fact_type: str
    dedup_key: str
    payload: dict
    confidence: float
    created_at: datetime
    evidence: list[EvidenceItem] = Field(default_factory=list)


@router.post("/process", response_model=ProcessResponse)
async def process(case_id: int, session: SessionDep) -> ProcessResponse:
    case = await session.get(Case, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    res = await process_case(case_id, session)
    return ProcessResponse(
        case_id=res.case_id,
        documents_total=res.documents_total,
        documents_processed=res.documents_processed,
        extractions_created=res.extractions_created,
        extractions_reused=res.extractions_reused,
        facts_created=res.facts_created,
        facts_reused=res.facts_reused,
        evidence_created=res.evidence_created,
        chunks_created=res.chunks_created,
        chunks_embedded=res.chunks_embedded,
        conflicts=res.conflicts,
    )


@router.get("/extractions", response_model=list[ExtractionResponse])
async def list_extractions(case_id: int, session: SessionDep) -> list[Extraction]:
    case = await session.get(Case, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    rows = (
        (
            await session.execute(
                select(Extraction)
                .join(Document, Document.id == Extraction.document_id)
                .where(Document.case_id == case_id)
                .order_by(Extraction.document_id, Extraction.id)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


@router.get("/facts", response_model=list[FactResponse])
async def list_facts(
    case_id: int,
    session: SessionDep,
    fact_type: str | None = None,
) -> list[FactResponse]:
    case = await session.get(Case, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    q = select(Fact).where(Fact.case_id == case_id)
    if fact_type:
        q = q.where(Fact.fact_type == fact_type)
    q = q.order_by(Fact.fact_type, Fact.id)

    facts = (await session.execute(q)).scalars().all()

    # Join evidence with document filenames for readability.
    fact_ids = [f.id for f in facts]
    if not fact_ids:
        return []

    ev_rows = (
        
            await session.execute(
                select(FactEvidence, Document.filename)
                .join(Document, Document.id == FactEvidence.document_id)
                .where(FactEvidence.fact_id.in_(fact_ids))
                .order_by(FactEvidence.id)
            )
        
    ).all()

    by_fact: dict[int, list[EvidenceItem]] = {}
    for ev, filename in ev_rows:
        by_fact.setdefault(ev.fact_id, []).append(
            EvidenceItem(
                document_id=ev.document_id,
                document_filename=filename,
                span=ev.span,
            )
        )

    return [
        FactResponse(
            id=f.id,
            case_id=f.case_id,
            fact_type=f.fact_type,
            dedup_key=f.dedup_key,
            payload=f.payload,
            confidence=float(f.confidence),
            created_at=f.created_at,
            evidence=by_fact.get(f.id, []),
        )
        for f in facts
    ]

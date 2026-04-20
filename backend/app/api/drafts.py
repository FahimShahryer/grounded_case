"""Draft endpoints: generate and fetch grounded drafts."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import SessionDep
from app.db.tables import Case, Draft, Edit
from app.models.draft import DraftContent
from app.models.enums import DraftType
from app.pipeline.generate import generate_draft

cases_router = APIRouter(prefix="/api/cases/{case_id}", tags=["drafts"])
drafts_router = APIRouter(prefix="/api/drafts", tags=["drafts"])


class DraftCreate(BaseModel):
    draft_type: DraftType


class DraftOut(BaseModel):
    id: int
    case_id: int
    draft_type: str
    template_version: int
    model: str
    content: DraftContent
    content_markdown: str
    parent_draft_id: int | None
    created_at: datetime


def _to_out(draft: Draft) -> DraftOut:
    return DraftOut(
        id=draft.id,
        case_id=draft.case_id,
        draft_type=draft.draft_type,
        template_version=draft.template_version,
        model=draft.model,
        content=DraftContent.model_validate(draft.content),
        content_markdown=draft.content_markdown,
        parent_draft_id=draft.parent_draft_id,
        created_at=draft.created_at,
    )


@cases_router.post("/drafts", response_model=DraftOut, status_code=201)
async def create_draft(
    case_id: int, payload: DraftCreate, session: SessionDep
) -> DraftOut:
    case = await session.get(Case, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")

    draft = await generate_draft(
        case_id=case_id, draft_type=payload.draft_type, session=session
    )
    return _to_out(draft)


@cases_router.get("/drafts", response_model=list[DraftOut])
async def list_drafts_for_case(case_id: int, session: SessionDep) -> list[DraftOut]:
    case = await session.get(Case, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    rows = (
        (
            await session.execute(
                select(Draft).where(Draft.case_id == case_id).order_by(Draft.id.desc())
            )
        )
        .scalars()
        .all()
    )
    return [_to_out(d) for d in rows]


@drafts_router.get("/{draft_id}", response_model=DraftOut)
async def get_draft(draft_id: int, session: SessionDep) -> DraftOut:
    draft = await session.get(Draft, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="Draft not found")
    return _to_out(draft)


class EditCreate(BaseModel):
    operator_id: str | None = None
    operator_version: DraftContent
    rationale: str | None = None


class EditOut(BaseModel):
    id: int
    draft_id: int
    operator_id: str | None
    operator_version: DraftContent
    structured_diff: dict
    rationale: str | None
    created_at: datetime


@drafts_router.post("/{draft_id}/edits", response_model=EditOut, status_code=201)
async def save_edit(
    draft_id: int, payload: EditCreate, session: SessionDep
) -> EditOut:
    """Persist an operator-edited draft version.

    The structured_diff is stored as an empty placeholder here; Step 9's
    pattern miner computes the diff on demand when mining rules. Keeping
    the full `operator_version` is what matters for learning.
    """
    draft = await session.get(Draft, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="Draft not found")

    edit = Edit(
        draft_id=draft_id,
        operator_id=payload.operator_id,
        operator_version=payload.operator_version.model_dump(mode="json"),
        structured_diff={},  # filled in by Step 9
        rationale=payload.rationale,
    )
    session.add(edit)
    await session.commit()
    await session.refresh(edit)
    return EditOut(
        id=edit.id,
        draft_id=edit.draft_id,
        operator_id=edit.operator_id,
        operator_version=DraftContent.model_validate(edit.operator_version),
        structured_diff=edit.structured_diff,
        rationale=edit.rationale,
        created_at=edit.created_at,
    )


@drafts_router.get("/{draft_id}/edits", response_model=list[EditOut])
async def list_edits(draft_id: int, session: SessionDep) -> list[EditOut]:
    rows = (
        (
            await session.execute(
                select(Edit).where(Edit.draft_id == draft_id).order_by(Edit.id.desc())
            )
        )
        .scalars()
        .all()
    )
    return [
        EditOut(
            id=e.id,
            draft_id=e.draft_id,
            operator_id=e.operator_id,
            operator_version=DraftContent.model_validate(e.operator_version),
            structured_diff=e.structured_diff,
            rationale=e.rationale,
            created_at=e.created_at,
        )
        for e in rows
    ]

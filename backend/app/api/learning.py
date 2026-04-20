"""Learning endpoints: mine, list patterns, list templates."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import SessionDep
from app.db.tables import Pattern, Template
from app.learning.mine import run_miner

router = APIRouter(prefix="/api/learning", tags=["learning"])


class MineResponse(BaseModel):
    signals_collected: int
    patterns_upserted: int
    templates_bumped: list[str]


class PatternOut(BaseModel):
    id: int
    scope: str
    draft_type: str | None
    section_id: str | None
    rule_when: str
    rule_must: str
    confidence: float
    supporting_edit_ids: list[int] = Field(default_factory=list)
    version: int
    active: bool
    created_at: datetime
    updated_at: datetime


class TemplateOut(BaseModel):
    id: int
    draft_type: str
    version: int
    manifest: dict
    active: bool
    created_at: datetime


@router.post("/mine", response_model=MineResponse)
async def mine(session: SessionDep) -> MineResponse:
    res = await run_miner(session)
    return MineResponse(
        signals_collected=res.signals_collected,
        patterns_upserted=res.patterns_upserted,
        templates_bumped=res.templates_bumped,
    )


@router.get("/patterns", response_model=list[PatternOut])
async def list_patterns(session: SessionDep) -> list[PatternOut]:
    rows = (
        (await session.execute(select(Pattern).order_by(Pattern.confidence.desc(), Pattern.id)))
        .scalars()
        .all()
    )
    return [
        PatternOut(
            id=p.id,
            scope=p.scope,
            draft_type=p.draft_type,
            section_id=p.section_id,
            rule_when=p.rule_when,
            rule_must=p.rule_must,
            confidence=float(p.confidence),
            supporting_edit_ids=p.supporting_edit_ids or [],
            version=p.version,
            active=p.active,
            created_at=p.created_at,
            updated_at=p.updated_at,
        )
        for p in rows
    ]


@router.get("/templates", response_model=list[TemplateOut])
async def list_templates(session: SessionDep) -> list[TemplateOut]:
    rows = (
        (await session.execute(select(Template).order_by(Template.id.desc())))
        .scalars()
        .all()
    )
    return [
        TemplateOut(
            id=t.id,
            draft_type=t.draft_type,
            version=t.version,
            manifest=t.manifest,
            active=t.active,
            created_at=t.created_at,
        )
        for t in rows
    ]

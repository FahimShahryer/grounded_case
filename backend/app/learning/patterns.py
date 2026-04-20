"""Pattern store helpers — upsert + active-pattern retrieval."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.tables import Pattern
from app.models.enums import DraftType


async def upsert_pattern(
    *,
    scope: str,
    draft_type: str | None,
    section_id: str | None,
    rule_when: str,
    rule_must: str,
    confidence: float,
    supporting_edit_ids: list[int],
    session: AsyncSession,
) -> Pattern:
    """Insert or reinforce a pattern by (draft_type, section_id, rule_must)."""
    q = select(Pattern).where(
        Pattern.rule_must == rule_must,
    )
    if draft_type is None:
        q = q.where(Pattern.draft_type.is_(None))
    else:
        q = q.where(Pattern.draft_type == draft_type)
    if section_id is None:
        q = q.where(Pattern.section_id.is_(None))
    else:
        q = q.where(Pattern.section_id == section_id)

    existing = (await session.execute(q)).scalar_one_or_none()

    if existing is not None:
        # Reinforcement: bump confidence (clamped), merge supporting edits.
        merged = sorted(set([*existing.supporting_edit_ids, *supporting_edit_ids]))
        new_conf = min(1.0, float(existing.confidence) + 0.05)
        existing.confidence = Decimal(str(round(new_conf, 3)))
        existing.supporting_edit_ids = merged
        existing.version += 1
        existing.active = True
        return existing

    row = Pattern(
        scope=scope,
        draft_type=draft_type,
        section_id=section_id,
        rule_when=rule_when,
        rule_must=rule_must,
        confidence=Decimal(str(round(confidence, 3))),
        supporting_edit_ids=supporting_edit_ids,
        version=1,
        active=True,
    )
    session.add(row)
    await session.flush()
    return row


async def active_patterns(
    *,
    session: AsyncSession,
    draft_type: DraftType | None = None,
    section_id: str | None = None,
    min_confidence: float = 0.5,
) -> list[Pattern]:
    """Active patterns applicable to the (draft_type, section_id) scope.

    Universal patterns (draft_type=NULL) and section-wildcard patterns
    (section_id=NULL) are included.
    """
    q = select(Pattern).where(
        Pattern.active.is_(True),
        Pattern.confidence >= Decimal(str(min_confidence)),
    )
    if draft_type is not None:
        q = q.where(
            or_(Pattern.draft_type == draft_type.value, Pattern.draft_type.is_(None))
        )
    if section_id is not None:
        q = q.where(
            or_(Pattern.section_id == section_id, Pattern.section_id.is_(None))
        )
    q = q.order_by(Pattern.confidence.desc(), Pattern.id)
    return list((await session.execute(q)).scalars().all())

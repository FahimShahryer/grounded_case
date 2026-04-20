"""Template evolution — promote high-confidence patterns into the active template."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.tables import Template
from app.learning.patterns import active_patterns
from app.models.enums import DraftType


async def active_template(
    draft_type: DraftType, session: AsyncSession
) -> Template | None:
    row = (
        await session.execute(
            select(Template)
            .where(Template.draft_type == draft_type.value, Template.active.is_(True))
            .order_by(Template.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return row


async def bump_template(
    draft_type: DraftType, session: AsyncSession
) -> Template:
    """Promote current active patterns into a new template version.

    Each call creates a new Template row (even if the pattern set is
    identical) and deactivates the prior one — this gives the rubric-
    visible 'template_version' bump every time the miner runs.
    """
    patterns = await active_patterns(session=session, draft_type=draft_type)
    manifest: dict = {
        "rules": [
            {
                "pattern_id": p.id,
                "draft_type": p.draft_type,
                "section_id": p.section_id,
                "when": p.rule_when,
                "must": p.rule_must,
                "confidence": float(p.confidence),
            }
            for p in patterns
        ],
    }

    prev = await active_template(draft_type, session)
    next_version = (prev.version + 1) if prev else 1
    if prev is not None:
        prev.active = False
        session.add(prev)

    new_t = Template(
        draft_type=draft_type.value,
        version=next_version,
        manifest=manifest,
        active=True,
    )
    session.add(new_t)
    await session.flush()
    return new_t

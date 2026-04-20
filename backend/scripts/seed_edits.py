"""Seed the two sample operator edits from `sample_edits.json` into the DB.

For each edit we:
  1. Find (or create) a Draft of the matching draft_type for case #1.
  2. Insert an Edit row tagged with `source=sample_edits.json` and
     `key_edits_raw=[…]` so the miner can read them directly as
     pre-classified rule signals.

Idempotent: re-running replaces prior sample-sourced edits.

Usage:
    docker compose exec backend python -m scripts.seed_edits
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy import select

from app.db.session import SessionLocal
from app.db.tables import Case, Draft, Edit

DATA_DIR = Path("/app/data/rodriguez")


async def _find_or_create_seed_draft(case: Case, draft_type: str, session) -> Draft:
    """Use any existing draft of this type, else create a minimal placeholder."""
    existing = (
        await session.execute(
            select(Draft)
            .where(Draft.case_id == case.id, Draft.draft_type == draft_type)
            .order_by(Draft.id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    # Placeholder draft — the miner only cares about (draft_type, case_id).
    placeholder = Draft(
        case_id=case.id,
        draft_type=draft_type,
        template_id=None,
        template_version=1,
        model="seed",
        content={"header": {}, "sections": []},
        content_markdown="(seed placeholder)",
    )
    session.add(placeholder)
    await session.commit()
    await session.refresh(placeholder)
    return placeholder


async def main() -> None:
    path = DATA_DIR / "sample_edits.json"
    if not path.exists():
        print(f"[seed-edits] ERROR: {path} not found", file=sys.stderr)
        sys.exit(1)

    edits = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(edits, list) or not edits:
        print("[seed-edits] ERROR: sample_edits.json is empty or not a list", file=sys.stderr)
        sys.exit(1)

    async with SessionLocal() as session:
        case = (await session.execute(select(Case).limit(1))).scalar_one_or_none()
        if case is None:
            print("[seed-edits] ERROR: no case found. Run `make seed` first.", file=sys.stderr)
            sys.exit(1)

        # Remove any prior sample-sourced edits so reruns are clean.
        prev = (
            (
                await session.execute(
                    select(Edit).where(Edit.operator_id == "sample")
                )
            )
            .scalars()
            .all()
        )
        for e in prev:
            await session.delete(e)
        if prev:
            await session.commit()

        for item in edits:
            draft_type = item["draft_type"]
            key_edits = item.get("key_edits") or []
            context = item.get("context") or ""

            draft = await _find_or_create_seed_draft(case, draft_type, session)

            row = Edit(
                draft_id=draft.id,
                operator_id="sample",
                operator_version={
                    "header": {},
                    "sections": [],
                    "_source_draft_markdown": item.get("system_draft", ""),
                    "_operator_markdown": item.get("operator_edited_version", ""),
                },
                structured_diff={
                    "source": "sample_edits.json",
                    "key_edits_raw": key_edits,
                    "context": context,
                },
                rationale="Sample operator edit fixture",
            )
            session.add(row)
            await session.commit()
            print(
                f"[seed-edits] {draft_type}: inserted edit "
                f"(id={row.id}, {len(key_edits)} key_edits)"
            )

        print("[seed-edits] Done.")


if __name__ == "__main__":
    asyncio.run(main())

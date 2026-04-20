"""Pattern miner — turn classified rule signals into durable Patterns.

Input sources:
  1. Edit rows where `structured_diff.key_edits_raw` is populated
     (that's how the sample_edits.json seed is loaded — pre-tagged
     signals straight from the fixture).
  2. Edit rows with a real `operator_version` → we compute a diff
     against the parent Draft's content and classify each change.

Both streams yield ClassifiedSignal[]. Signals for the same draft_type
are clustered + generalized together into MinedPattern[] via one LLM
call. Each resulting pattern is then upserted into the `patterns` table
(reinforcing existing entries), and a new `templates` row is written
for every draft_type touched.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.tables import Draft, Edit, Template
from app.learning.classify import classify_signals
from app.learning.diff import diff_drafts
from app.learning.patterns import upsert_pattern
from app.learning.templates import bump_template
from app.llm import client as llm
from app.models.draft import DraftContent
from app.models.enums import DraftType, EditChangeKind, LlmPurpose, PatternScope

# --------------------------------------------------------------------------
# Miner-facing schemas


class MinedPattern(BaseModel):
    scope: PatternScope = PatternScope.firm
    draft_type: DraftType | None = Field(
        default=None,
        description="None means the rule applies across every draft type.",
    )
    section_id: str | None = Field(
        default=None,
        description="None means the rule applies to every section of the draft.",
    )
    rule_when: str
    rule_must: str
    confidence: float = Field(ge=0.0, le=1.0)
    supporting_signal_ids: list[int] = Field(
        default_factory=list,
        description="0-based indices into the provided signals list.",
    )


class MinerOutput(BaseModel):
    patterns: list[MinedPattern]


_MINER_SYSTEM_PROMPT = """You are a pattern miner. You receive a list of
operator edit signals — short descriptions of what operators changed in
a draft. Generalize these into DURABLE RULES that should apply to
future drafts.

Each output MinedPattern must:
- Be specific enough to verify ('every lien block must include
  instrument_number', NOT 'improve liens').
- Be generalized — one rule per distinct preference, not one rule per
  input signal.
- Cite its supporting signals by 0-based index via supporting_signal_ids.
- Have a realistic confidence (0.6-0.95) based on how clearly the
  signals support the rule. Rules supported by multiple signals get
  higher confidence.
- Use draft_type=null when the rule generalizes across draft types
  (e.g., "always flag critical items with an ACTION REQUIRED badge").
- Use section_id=null when the rule applies to every section of the
  draft (e.g., "include evidence citations on every block").

Aim for 4-8 patterns per call: fewer than one-per-signal (so you're
generalizing), more than one total (so you capture variety).
"""


# --------------------------------------------------------------------------


@dataclass
class Signal:
    """One rule-class edit signal with provenance."""

    text: str
    edit_id: int
    draft_type: DraftType


async def _load_signals_for_edit(
    edit: Edit, draft: Draft, session: AsyncSession
) -> list[Signal]:
    """Extract rule-class signals from a single Edit row."""
    diff_struct = edit.structured_diff or {}
    draft_type = DraftType(draft.draft_type)

    # Fast path: sample_edits.json seeds include `key_edits_raw` —
    # treat each as a pre-classified rule signal.
    key_edits = diff_struct.get("key_edits_raw")
    if isinstance(key_edits, list) and key_edits:
        return [
            Signal(text=str(t), edit_id=edit.id, draft_type=draft_type)
            for t in key_edits
        ]

    # Slow path: compute diff → classify → keep rule-class only.
    try:
        sys_content = DraftContent.model_validate(draft.content)
        op_content = DraftContent.model_validate(edit.operator_version)
    except Exception:
        return []

    diff = diff_drafts(sys_content, op_content)
    if not diff.summary:
        return []

    classified = await classify_signals(
        diff.summary,
        context={"draft_type": draft_type.value},
        case_id=draft.case_id,
    )
    return [
        Signal(text=c.summary or diff.summary[c.index], edit_id=edit.id, draft_type=draft_type)
        for c in classified
        if c.kind == EditChangeKind.rule
    ]


async def _mine_for_draft_type(
    signals: list[Signal], case_id: int | None
) -> list[MinedPattern]:
    if not signals:
        return []
    if not llm.has_api_key():
        # Fallback: one pattern per signal, generic scope, low confidence.
        return [
            MinedPattern(
                scope=PatternScope.firm,
                draft_type=signals[0].draft_type,
                section_id=None,
                rule_when=f"when generating {signals[0].draft_type.value}",
                rule_must=s.text,
                confidence=0.5,
                supporting_signal_ids=[i],
            )
            for i, s in enumerate(signals)
        ]

    messages = [
        {"role": "system", "content": _MINER_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Draft type: {signals[0].draft_type.value}\n\n"
                f"Signals ({len(signals)}):\n"
                + "\n".join(f"[{i}] {s.text}" for i, s in enumerate(signals))
            ),
        },
    ]
    out = await llm.parse(
        purpose=LlmPurpose.mine_pattern,
        model=settings.model_primary,
        messages=messages,
        response_format=MinerOutput,
        case_id=case_id,
    )
    return list(out.patterns)


# --------------------------------------------------------------------------
# Public API


@dataclass
class MineResult:
    signals_collected: int
    patterns_upserted: int
    templates_bumped: list[str]


async def run_miner(
    session: AsyncSession,
    case_id: int | None = None,
) -> MineResult:
    """Run the miner across ALL stored edits. Idempotent: re-running
    reinforces existing patterns and bumps template versions.
    """
    rows = (
        
            await session.execute(
                select(Edit, Draft).join(Draft, Draft.id == Edit.draft_id)
            )
        
    ).all()

    # Gather + group signals by draft_type
    by_type: dict[DraftType, list[Signal]] = {}
    for edit, draft in rows:
        sigs = await _load_signals_for_edit(edit, draft, session)
        for s in sigs:
            by_type.setdefault(s.draft_type, []).append(s)

    total_signals = sum(len(v) for v in by_type.values())

    # Mine each group independently; preserve scope across types via null draft_type output
    upserted = 0
    draft_types_touched: set[DraftType] = set()
    for draft_type, sigs in by_type.items():
        mined = await _mine_for_draft_type(sigs, case_id=case_id)
        draft_types_touched.add(draft_type)
        for p in mined:
            # Resolve support signal indices back to edit IDs.
            supporting_edit_ids = sorted(
                {sigs[i].edit_id for i in p.supporting_signal_ids if 0 <= i < len(sigs)}
            )
            if not supporting_edit_ids:
                supporting_edit_ids = [sigs[0].edit_id]

            # Scope: if miner declared a specific draft_type, honor it;
            # else use the group's draft_type (keeps the pattern scoped).
            dt = p.draft_type.value if p.draft_type is not None else draft_type.value
            # Allow the LLM to explicitly declare a universal pattern via the empty string.
            if dt == "":
                dt = None  # type: ignore[assignment]

            await upsert_pattern(
                scope=p.scope.value,
                draft_type=dt,
                section_id=p.section_id,
                rule_when=p.rule_when,
                rule_must=p.rule_must,
                confidence=p.confidence,
                supporting_edit_ids=supporting_edit_ids,
                session=session,
            )
            upserted += 1

    # Update templates for every draft type we touched.
    bumped: list[str] = []
    for dt in draft_types_touched:
        t: Template = await bump_template(dt, session)
        bumped.append(f"{dt.value}:v{t.version}")

    await session.commit()
    return MineResult(
        signals_collected=total_signals,
        patterns_upserted=upserted,
        templates_bumped=bumped,
    )

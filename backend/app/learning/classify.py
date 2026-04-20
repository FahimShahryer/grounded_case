"""Classify each change in an EditDiff as fix / rule / case-specific.

Only `rule`-class changes become candidates for pattern mining — they
represent operator preferences the system should adopt going forward.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.config import settings
from app.learning.diff import EditDiff
from app.llm import client as llm
from app.models.enums import EditChangeKind, LlmPurpose


class ClassifiedSignal(BaseModel):
    index: int = Field(description="0-based index into the input signal list.")
    kind: EditChangeKind
    summary: str = Field(description="One-sentence generalization ('rule' kind only).")
    reason: str = ""


class ClassificationOutput(BaseModel):
    signals: list[ClassifiedSignal]


_SYSTEM_PROMPT = """You classify operator edits into three kinds:

- `fix`: the operator corrected an extraction or rendering error
  (wrong amount, wrong date, typo). This is a signal for the extractor,
  NOT a general rule.
- `rule`: the operator applied a consistent preference that should
  generalize to future drafts (e.g., "always include instrument
  numbers", "always label sections clearly"). Give a one-sentence
  summary that generalizes the rule.
- `case_specific`: the edit only makes sense for this particular case
  (unique party-naming decision, case-specific note). Do NOT generalize.

Return one ClassifiedSignal per input signal, preserving `index`.
Rules are the gold; be generous in marking generic preferences as `rule`.
"""


async def classify_signals(
    signals: list[str],
    context: dict | None = None,
    case_id: int | None = None,
) -> list[ClassifiedSignal]:
    """Classify a list of signal strings. Same order as input."""
    if not signals:
        return []
    if not llm.has_api_key():
        # Fallback: mark everything as rule with the raw summary.
        return [
            ClassifiedSignal(
                index=i,
                kind=EditChangeKind.rule,
                summary=s,
                reason="no LLM key; treated as rule",
            )
            for i, s in enumerate(signals)
        ]

    ctx = context or {}
    user = (
        f"Context: {ctx}\n\n"
        f"Signals ({len(signals)}):\n"
        + "\n".join(f"[{i}] {s}" for i, s in enumerate(signals))
    )
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]
    result = await llm.parse(
        purpose=LlmPurpose.diff,  # closest existing purpose
        model=settings.model_cheap,
        messages=messages,
        response_format=ClassificationOutput,
        case_id=case_id,
    )
    # Guard: ensure every input has a classification, order by index.
    classified = {s.index: s for s in result.signals if 0 <= s.index < len(signals)}
    out: list[ClassifiedSignal] = []
    for i, raw in enumerate(signals):
        if i in classified:
            out.append(classified[i])
        else:
            out.append(
                ClassifiedSignal(
                    index=i,
                    kind=EditChangeKind.rule,
                    summary=raw,
                    reason="missing from LLM response; defaulting to rule",
                )
            )
    return out


async def classify_edit_diff(
    diff: EditDiff, context: dict | None = None, case_id: int | None = None
) -> list[ClassifiedSignal]:
    """Classify every change in an EditDiff."""
    return await classify_signals(diff.summary, context=context, case_id=case_id)

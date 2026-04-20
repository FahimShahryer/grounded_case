"""Run the before/after evaluation and write outputs/evaluation.md.

Also dumps:
  outputs/v1_before_learning/{draft_type}.md
  outputs/v2_after_learning/{draft_type}.md
  outputs/patterns.yaml
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy import select

from app.db.session import SessionLocal
from app.db.tables import Case, Pattern
from app.learning.evaluate import CompareRow, evaluate_case

OUTPUTS = Path("/app/outputs")


def _row(label: str, v1: float, v2: float, counts_v1: tuple[int, int], counts_v2: tuple[int, int], *, lower_better: bool = False) -> str:
    delta = v2 - v1
    arrow = ""
    if delta > 0.001:
        arrow = " ↑" if not lower_better else " ↓"
    elif delta < -0.001:
        arrow = " ↓" if not lower_better else " ↑"
    return (
        f"| {label:30} | {v1:.2f} ({counts_v1[0]}/{counts_v1[1]}) "
        f"| {v2:.2f} ({counts_v2[0]}/{counts_v2[1]}) "
        f"| {delta:+.2f}{arrow} |"
    )


def render_table(rows: list[CompareRow]) -> str:
    out: list[str] = []
    out.append("# Evaluation — v1 vs v2\n")
    out.append(
        "`v1` is the pre-learning baseline (generated with no learned "
        "patterns). `v2` is post-learning (the current active template "
        "with mined rules enforced by the verifier retry loop). "
        "Both run through diskcache so repeat evaluations are free.\n"
    )
    for cr in rows:
        v1 = cr.v1
        v2 = cr.v2
        out.append(f"\n## {cr.draft_type}")
        out.append(
            f"v1: draft #{v1.draft_id} (template_version={v1.template_version}) · "
            f"v2: draft #{v2.draft_id} (template_version={v2.template_version})\n"
        )
        out.append("| Metric | v1 | v2 | Δ |")
        out.append("|---|---|---|---|")
        out.append(
            _row(
                "Grounded-claim coverage",
                v1.coverage,
                v2.coverage,
                v1.coverage_counts,
                v2.coverage_counts,
            )
        )
        out.append(
            _row(
                "Structural fidelity",
                v1.structural,
                v2.structural,
                v1.structural_counts,
                v2.structural_counts,
            )
        )
        out.append(
            _row(
                "Rule compliance",
                v1.rule_compliance,
                v2.rule_compliance,
                v1.rule_counts,
                v2.rule_counts,
            )
        )
        out.append(
            _row(
                "Citation accuracy",
                v1.citation_accuracy,
                v2.citation_accuracy,
                v1.citation_counts,
                v2.citation_counts,
            )
        )
        out.append(
            _row(
                "Hallucination rate",
                v1.hallucination_rate,
                v2.hallucination_rate,
                v1.hallucination_counts,
                v2.hallucination_counts,
                lower_better=True,
            )
        )
    return "\n".join(out) + "\n"


async def _write_patterns_yaml(session) -> None:
    rows = (
        (
            await session.execute(
                select(Pattern).order_by(Pattern.confidence.desc(), Pattern.id)
            )
        )
        .scalars()
        .all()
    )
    lines: list[str] = []
    for p in rows:
        lines.append(f"- id: {p.id}")
        lines.append(f"  scope: {p.scope}")
        lines.append(f"  draft_type: {p.draft_type or '~'}")
        lines.append(f"  section_id: {p.section_id or '~'}")
        lines.append(f"  confidence: {float(p.confidence):.3f}")
        lines.append(f"  version: {p.version}")
        lines.append(f"  active: {str(p.active).lower()}")
        lines.append(f"  rule_when: {p.rule_when!r}")
        lines.append(f"  rule_must: {p.rule_must!r}")
        lines.append(
            "  supporting_edit_ids: ["
            + ", ".join(str(x) for x in (p.supporting_edit_ids or []))
            + "]"
        )
        lines.append("")
    (OUTPUTS / "patterns.yaml").write_text("\n".join(lines), encoding="utf-8")


def _dump_draft(dir_: Path, draft) -> None:
    dir_.mkdir(parents=True, exist_ok=True)
    (dir_ / f"{draft.draft_type}.md").write_text(draft.content_markdown, encoding="utf-8")
    (dir_ / f"{draft.draft_type}.json").write_text(
        json.dumps(draft.content, indent=2), encoding="utf-8"
    )


async def main() -> None:
    OUTPUTS.mkdir(exist_ok=True)

    async with SessionLocal() as session:
        case = (await session.execute(select(Case).limit(1))).scalar_one_or_none()
        if case is None:
            print("No cases. Run `make seed` first.", file=sys.stderr)
            sys.exit(1)

        result = await evaluate_case(case.id, session)

        # Re-read both drafts from DB to dump their markdown into outputs/.
        from app.db.tables import Draft
        for cr in result.rows:
            for version_name, metrics in [("v1_before_learning", cr.v1), ("v2_after_learning", cr.v2)]:
                draft = await session.get(Draft, metrics.draft_id)
                if draft is not None:
                    _dump_draft(OUTPUTS / version_name, draft)

        await _write_patterns_yaml(session)

    table = render_table(result.rows)
    (OUTPUTS / "evaluation.md").write_text(table, encoding="utf-8")
    print(table)


if __name__ == "__main__":
    asyncio.run(main())

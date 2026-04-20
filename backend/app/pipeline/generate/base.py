"""Section-by-section grounded generation.

Flow:
  plan_for(draft_type)
    ↓
  for each SectionQuery in plan:
    build_evidence_pack()
      ↓
    generate_section()
      ↓  (may regenerate up to MAX_RETRIES times if verifier rejects)
    verify_section()
      ↓
  DraftContent(sections=[...]) → render_draft_markdown() → persist to `drafts`
"""

from __future__ import annotations

import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.tables import Case, Draft, Pattern
from app.learning.patterns import active_patterns
from app.learning.templates import active_template
from app.llm import client as llm
from app.models.draft import DraftContent, DraftSection
from app.models.enums import DraftType, LlmPurpose
from app.models.evidence_pack import EvidencePack
from app.pipeline.evidence import build_evidence_pack
from app.pipeline.generate.guidance import guidance_for
from app.pipeline.generate.render import render_draft_markdown
from app.pipeline.generate.verify import verify_section
from app.pipeline.plans import SectionQuery, plan_for

log = logging.getLogger(__name__)

_MAX_RETRIES = 2


# ------------------------------------------------------------------ prompts


_SECTION_SYSTEM_PROMPT = """You generate one section of a legal-case draft.

You will receive:
  - Case identifiers (case number, borrower, property).
  - A SectionQuery describing which section to write (id, heading, description).
  - An EvidencePack: `structured_facts` (canonical facts from the knowledge
    graph) and `text_evidence` (ranked verbatim chunks) and `known_gaps`.
  - Guidance text with per-section expectations (block shape, badges).

Output a structured DraftSection. NON-NEGOTIABLE RULES:

1. Every factual claim you write MUST be grounded in the evidence pack —
   either in a `structured_facts` payload or verbatim in `text_evidence`.
2. Every DraftBlock MUST have at least one Citation with at least one
   SourceSpan. Cite by copying file/line_start/line_end/raw_text from the
   evidence you used.
3. DO NOT invent facts. If the evidence is silent on a detail, omit it.
4. Preserve precision — use exact amounts, dates, instrument numbers, and
   party names from the evidence.
5. If the evidence is empty for this section, set abstained=true, write a
   short body like "No <topic> identified in source materials.", and leave
   blocks=[].
6. Use badges (short uppercase tags) for status: "ASSIGNED", "DELINQUENT",
   "ACTION REQUIRED", "URGENT", "HIGH". Use them when the guidance says so.
7. fields is a list of {key, value} rows — human-readable, short values.
8. Temporal updates: if a structured fact's payload contains a
   `previous_values` list, the fact has been UPDATED over time. Present
   the current value prominently, and explicitly call out the change
   in a short note so the operator can see what changed. Examples:
     - notes: "Payoff updated from $487,920 (Mar 15) to $490,500 (Mar 20)."
     - field: {"key": "Previous Payoff", "value": "$487,920 (Mar 15, 2026)"}
   Cite both the current and the prior evidence spans where available.
"""


# ------------------------------------------------------------------ helpers


def _fmt_evidence(evidence: EvidencePack) -> str:
    lines: list[str] = []

    if evidence.structured_facts:
        lines.append("STRUCTURED FACTS (from knowledge graph):")
        for i, f in enumerate(evidence.structured_facts):
            lines.append(
                f"  [F{i}] fact_type={f.fact_type} dedup_key={f.dedup_key}"
            )
            lines.append(f"       payload={json.dumps(f.payload, default=str)}")
            for sp in f.evidence_spans:
                lines.append(
                    f"       evidence: {sp.file}:L{sp.line_start}-{sp.line_end} "
                    f"(raw_text={sp.raw_text!r})"
                )
        lines.append("")

    if evidence.text_evidence:
        lines.append("TEXT EVIDENCE (ranked):")
        for i, e in enumerate(evidence.text_evidence):
            lines.append(
                f"  [T{i}] {e.filename}:L{e.line_start}-{e.line_end} "
                f"(rank={e.ranks}, score={e.score:.4f})"
            )
            lines.append(f"       text={e.text!r}")
        lines.append("")

    if evidence.known_gaps:
        lines.append("KNOWN GAPS (explicitly absent in source material):")
        for g in evidence.known_gaps:
            lines.append(f"  - {g}")
        lines.append("")

    if evidence.conflicts:
        lines.append("CONFLICTS (source documents disagree — hedge in output):")
        for c in evidence.conflicts:
            lines.append(f"  - {c.fact_type} {c.dedup_key}: {c.candidates}")
        lines.append("")

    return "\n".join(lines)


def _build_user_message(
    *,
    case: Case,
    section: SectionQuery,
    evidence: EvidencePack,
    guidance: str,
    correction: str | None = None,
) -> str:
    parts = [
        "CASE:",
        f"  case_number: {case.case_number}",
        f"  borrower: {case.borrower}",
        f"  property: {case.property_address}",
        f"  jurisdiction: {case.county or ''}{', ' if case.county and case.state else ''}{case.state or ''}",
        "",
        "SECTION TO GENERATE:",
        f"  id: {section.section_id}",
        f"  description: {section.description}",
        (f"  guidance: {guidance}" if guidance else "  guidance: (none)"),
        "",
        _fmt_evidence(evidence),
    ]
    if correction:
        parts.append("CORRECTION REQUIRED (your previous output was rejected):")
        parts.append(correction)
        parts.append("")
        parts.append("Regenerate this section fixing the issues above.")
    else:
        parts.append(
            "Generate a DraftSection. Remember: every block must cite evidence."
        )
    return "\n".join(parts)


def _abstain_section(section: SectionQuery) -> DraftSection:
    return DraftSection(
        id=section.section_id,
        heading=section.description.capitalize(),
        body=(
            f"No {section.description.lower()} identified in the source materials."
        ),
        blocks=[],
        citations=[],
        abstained=True,
    )


def _ensure_section_id(sec: DraftSection, expected_id: str) -> DraftSection:
    # If the LLM re-titled the id, normalize to what the plan expects.
    if sec.id != expected_id:
        return sec.model_copy(update={"id": expected_id})
    return sec


def _fmt_rules(patterns: list[Pattern]) -> str:
    if not patterns:
        return ""
    lines = [
        "",
        "LEARNED RULES (from prior operator edits — enforce, do not violate):",
    ]
    for p in patterns:
        conf = int(float(p.confidence) * 100)
        lines.append(
            f"  - [{p.id}, conf={conf}%] WHEN {p.rule_when} → MUST {p.rule_must}"
        )
    return "\n".join(lines)


# ------------------------------------------------------------------ public API


async def generate_section(
    *,
    case: Case,
    section: SectionQuery,
    evidence: EvidencePack,
    case_id: int,
    draft_type: DraftType,
    session: AsyncSession,
    use_patterns: bool = True,
) -> tuple[DraftSection, list[str]]:
    """Return (section, notes). notes lists any verification issues that remained."""
    if evidence.is_empty:
        return _abstain_section(section), []

    # Guidance is our Step-7 hand-written encoding of operator preferences.
    # The Step-9 pattern miner re-discovers these from real edits and adds
    # them back via `rules_block`. To make the v1 baseline genuinely naive
    # (so the learning-loop delta is honest), we skip guidance when
    # use_patterns=False as well — v1 then reflects "no learned preferences".
    guidance = guidance_for(draft_type, section.section_id) if use_patterns else ""
    patterns = (
        await active_patterns(
            session=session, draft_type=draft_type, section_id=section.section_id
        )
        if use_patterns
        else []
    )
    rules_block = _fmt_rules(patterns)

    system_prompt = _SECTION_SYSTEM_PROMPT + rules_block

    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": _build_user_message(
                case=case, section=section, evidence=evidence, guidance=guidance
            ),
        },
    ]

    last_section: DraftSection | None = None
    last_issues: list[str] = []

    for attempt in range(_MAX_RETRIES + 1):
        raw = await llm.parse(
            purpose=LlmPurpose.generate,
            model=settings.model_primary,
            messages=messages,
            response_format=DraftSection,
            case_id=case_id,
        )
        last_section = _ensure_section_id(raw, section.section_id)

        result = await verify_section(
            last_section, evidence, case_id=case_id, use_llm=True, rules=patterns
        )
        if result.all_supported:
            return last_section, []

        last_issues = [*result.unsupported_claims, *result.rule_violations]
        log.info(
            "Verifier rejected section=%s attempt=%d issues=%s",
            section.section_id,
            attempt,
            last_issues,
        )

        # Hand the LLM its previous answer + the correction and retry.
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": _build_user_message(
                    case=case,
                    section=section,
                    evidence=evidence,
                    guidance=guidance,
                    correction="\n".join(f"  - {i}" for i in last_issues),
                ),
            },
        ]

    # Out of retries — return the last attempt with notes; the generator
    # is intentionally forgiving here rather than crashing a user request.
    assert last_section is not None
    return last_section, last_issues


async def generate_draft(
    *,
    case_id: int,
    draft_type: DraftType,
    session: AsyncSession,
    use_patterns: bool = True,
) -> Draft:
    case = await session.get(Case, case_id)
    if case is None:
        raise ValueError(f"Case {case_id} not found")

    plan = plan_for(draft_type)
    sections: list[DraftSection] = []
    notes_by_section: dict[str, list[str]] = {}

    # Pin the draft to the current active template (if any) unless we're
    # deliberately producing a pre-learning baseline. template_version=0
    # signals "no patterns applied" (v1 baseline).
    template_id: int | None = None
    template_version = 0
    if use_patterns:
        template = await active_template(draft_type, session)
        template_version = template.version if template else 1
        template_id = template.id if template else None

    for section_query in plan.sections:
        evidence = await build_evidence_pack(case_id, section_query, session)
        sec, notes = await generate_section(
            case=case,
            section=section_query,
            evidence=evidence,
            case_id=case_id,
            draft_type=draft_type,
            session=session,
            use_patterns=use_patterns,
        )
        sections.append(sec)
        if notes:
            notes_by_section[section_query.section_id] = notes

    # Jurisdiction is already rendered from case.county/state — don't duplicate.
    header: dict[str, str] = {}
    if case.current_status:
        header["case_status"] = case.current_status
    if case.servicer:
        header["servicer"] = case.servicer

    content = DraftContent(header=header, sections=sections)
    markdown = render_draft_markdown(content, draft_type, case)

    draft = Draft(
        case_id=case_id,
        draft_type=draft_type.value,
        template_id=template_id,
        template_version=template_version,
        model=settings.model_primary,
        content=content.model_dump(mode="json"),
        content_markdown=markdown,
    )
    session.add(draft)
    await session.commit()
    await session.refresh(draft)

    # Stash verifier notes on the draft row's metadata if any survived retries.
    if notes_by_section:
        log.info("Draft %d created with unresolved verifier notes: %s", draft.id, notes_by_section)

    return draft

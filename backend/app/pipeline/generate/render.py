"""Render a structured DraftContent into operator-facing markdown.

Deterministic, no LLM. Produces inline citations in `[filename:Lstart-end]`
form next to every fact, and a "Sources" block at the bottom of each
section listing the cited files.
"""

from __future__ import annotations

from app.db.tables import Case
from app.models.draft import Citation, DraftBlock, DraftContent, DraftSection
from app.models.enums import DraftType

# ------------------------------------------------------------------ helpers


def _cite_str(cit: Citation) -> str:
    if not cit.spans:
        return ""
    parts = []
    for s in cit.spans:
        if s.line_start and s.line_end and s.line_start != s.line_end:
            parts.append(f"{s.file}:L{s.line_start}-{s.line_end}")
        elif s.line_start:
            parts.append(f"{s.file}:L{s.line_start}")
        else:
            parts.append(s.file)
    return f" [{'; '.join(parts)}]"


def _render_block(block: DraftBlock) -> list[str]:
    lines: list[str] = []

    head_bits: list[str] = []
    if block.title:
        head_bits.append(f"**{block.title}**")
    for b in block.badges:
        head_bits.append(f"`{b}`")
    if head_bits:
        lines.append(" ".join(head_bits))

    for f in block.fields:
        lines.append(f"- *{f.key}*: {f.value}")

    if block.notes:
        lines.append("")
        lines.append(f"> {block.notes}")

    if block.action_items:
        lines.append("")
        for ai in block.action_items:
            lines.append(f"- [ ] {ai}")

    # Citations after the block content.
    if block.citations:
        lines.append("")
        for cit in block.citations:
            cite_str = _cite_str(cit).strip(" []")
            if cite_str:
                lines.append(f"  — {cit.claim} *[{cite_str}]*")

    return lines


def _render_section(section: DraftSection) -> list[str]:
    lines: list[str] = [f"## {section.heading}", ""]
    if section.abstained:
        lines.append("_No evidence of this found in the source materials._")
        lines.append("")
        return lines
    if section.body:
        lines.append(section.body)
        lines.append("")
    for i, block in enumerate(section.blocks):
        if i > 0:
            lines.append("")
        lines.extend(_render_block(block))
    # Cross-section-level citations (rare but supported).
    for cit in section.citations:
        cite_str = _cite_str(cit).strip(" []")
        if cite_str:
            lines.append(f"- _{cit.claim}_ *[{cite_str}]*")
    lines.append("")
    return lines


# ------------------------------------------------------------------ top-level


_DRAFT_TYPE_TITLES: dict[DraftType, str] = {
    DraftType.title_review_summary: "Title Review Summary",
    DraftType.case_status_memo: "Case Status Memo",
    DraftType.document_checklist: "Document Checklist",
    DraftType.action_item_extract: "Action Item Extract",
}


def render_draft_markdown(
    content: DraftContent, draft_type: DraftType, case: Case
) -> str:
    title = _DRAFT_TYPE_TITLES.get(draft_type, draft_type.value)

    header_lines = [
        f"# {title} — {case.borrower} ({case.case_number})",
        "",
        f"**Property:** {case.property_address}  ",
    ]
    if case.county or case.state:
        header_lines.append(
            f"**Jurisdiction:** {case.county or ''}{', ' if case.county and case.state else ''}{case.state or ''}  "
        )
    for k, v in content.header.items():
        header_lines.append(f"**{k.replace('_', ' ').title()}:** {v}  ")
    header_lines.append("")

    section_lines: list[str] = []
    for sec in content.sections:
        section_lines.extend(_render_section(sec))

    return "\n".join(header_lines + section_lines).rstrip() + "\n"

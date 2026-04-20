"""Structured diff of two DraftContent objects.

Produces a typed list of changes at section / block / field granularity.
Used by the classifier + miner to turn a single edit into rule signals.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.models.draft import DraftBlock, DraftContent, DraftSection

__all__ = ["BlockChange", "EditDiff", "FieldChange", "SectionChange", "diff_drafts"]


ChangeOp = Literal["add", "remove", "edit", "reorder"]


class FieldChange(BaseModel):
    section_id: str
    block_index: int | None = None
    path: str  # "section.heading" | "block.title" | "block.field:Amount" | "block.badge:ASSIGNED" | ...
    op: ChangeOp
    before: str | None = None
    after: str | None = None


class BlockChange(BaseModel):
    section_id: str
    op: ChangeOp  # add | remove
    block_index_before: int | None = None
    block_index_after: int | None = None
    title: str | None = None
    block: DraftBlock | None = None


class SectionChange(BaseModel):
    op: ChangeOp  # add | remove | reorder
    section_id: str
    section: DraftSection | None = None


class EditDiff(BaseModel):
    section_changes: list[SectionChange] = Field(default_factory=list)
    block_changes: list[BlockChange] = Field(default_factory=list)
    field_changes: list[FieldChange] = Field(default_factory=list)

    @property
    def summary(self) -> list[str]:
        """One-line description of every change — fed to classifier/miner."""
        out: list[str] = []
        for c in self.section_changes:
            if c.op == "add":
                out.append(f"Added section '{c.section_id}'.")
            elif c.op == "remove":
                out.append(f"Removed section '{c.section_id}'.")
            elif c.op == "reorder":
                out.append(f"Reordered section '{c.section_id}'.")
        for c in self.block_changes:
            if c.op == "add":
                out.append(
                    f"Added block '{c.title or '(untitled)'}' to section '{c.section_id}'."
                )
            elif c.op == "remove":
                out.append(
                    f"Removed block '{c.title or '(untitled)'}' from section '{c.section_id}'."
                )
        for c in c_changes_iter(self.field_changes):
            out.append(c)
        return out


def c_changes_iter(changes: list[FieldChange]) -> list[str]:
    out: list[str] = []
    for c in changes:
        tag = f"section '{c.section_id}'"
        if c.block_index is not None:
            tag += f", block[{c.block_index}]"
        if c.op == "add":
            out.append(f"Added {c.path} in {tag}: {c.after!r}.")
        elif c.op == "remove":
            out.append(f"Removed {c.path} in {tag}: {c.before!r}.")
        elif c.op == "edit":
            out.append(f"Edited {c.path} in {tag}: {c.before!r} → {c.after!r}.")
    return out


# ---------------------------------------------------------------------------


def diff_drafts(system: DraftContent, operator: DraftContent) -> EditDiff:
    """Structured diff of two DraftContent objects.

    Sections are matched by `id`. Blocks within a matched section are
    matched by normalized title (first) else by index.
    """
    diff = EditDiff()

    sys_sections = {s.id: s for s in system.sections}
    op_sections = {s.id: s for s in operator.sections}

    # Section add/remove
    all_ids = list(dict.fromkeys([*sys_sections, *op_sections]))
    for sid in all_ids:
        if sid not in sys_sections:
            diff.section_changes.append(
                SectionChange(op="add", section_id=sid, section=op_sections[sid])
            )
            continue
        if sid not in op_sections:
            diff.section_changes.append(
                SectionChange(op="remove", section_id=sid, section=sys_sections[sid])
            )
            continue

        sys_s = sys_sections[sid]
        op_s = op_sections[sid]

        # Section reorder detection
        sys_idx = next(i for i, s in enumerate(system.sections) if s.id == sid)
        op_idx = next(i for i, s in enumerate(operator.sections) if s.id == sid)
        if sys_idx != op_idx:
            diff.section_changes.append(
                SectionChange(op="reorder", section_id=sid, section=op_s)
            )

        # Heading / body / abstained
        if sys_s.heading != op_s.heading:
            diff.field_changes.append(
                FieldChange(
                    section_id=sid,
                    path="section.heading",
                    op="edit",
                    before=sys_s.heading,
                    after=op_s.heading,
                )
            )
        if (sys_s.body or "") != (op_s.body or ""):
            diff.field_changes.append(
                FieldChange(
                    section_id=sid,
                    path="section.body",
                    op="edit",
                    before=sys_s.body or "",
                    after=op_s.body or "",
                )
            )

        # Block diff
        _diff_blocks(sid, sys_s.blocks, op_s.blocks, diff)

    return diff


def _norm_title(t: str | None) -> str:
    return (t or "").strip().lower()


def _diff_blocks(
    section_id: str,
    sys_blocks: list[DraftBlock],
    op_blocks: list[DraftBlock],
    diff: EditDiff,
) -> None:
    """Match sys_blocks to op_blocks by normalized title; unmatched = add/remove."""
    sys_by_title: dict[str, list[tuple[int, DraftBlock]]] = {}
    for i, b in enumerate(sys_blocks):
        sys_by_title.setdefault(_norm_title(b.title), []).append((i, b))
    op_by_title: dict[str, list[tuple[int, DraftBlock]]] = {}
    for i, b in enumerate(op_blocks):
        op_by_title.setdefault(_norm_title(b.title), []).append((i, b))

    used_sys: set[int] = set()
    used_op: set[int] = set()

    # Match by title (first same-title pair each iteration)
    for title, op_list in op_by_title.items():
        if not title:
            continue
        sys_list = sys_by_title.get(title) or []
        pairs = min(len(sys_list), len(op_list))
        for k in range(pairs):
            sys_i, sys_b = sys_list[k]
            op_i, op_b = op_list[k]
            used_sys.add(sys_i)
            used_op.add(op_i)
            _diff_single_block(section_id, sys_i, sys_b, op_b, diff)

    # Then try to match untitled-or-unmatched pairs by index
    remaining_sys = [(i, sys_blocks[i]) for i in range(len(sys_blocks)) if i not in used_sys]
    remaining_op = [(i, op_blocks[i]) for i in range(len(op_blocks)) if i not in used_op]
    pairs = min(len(remaining_sys), len(remaining_op))
    for k in range(pairs):
        sys_i, sys_b = remaining_sys[k]
        op_i, op_b = remaining_op[k]
        _diff_single_block(section_id, sys_i, sys_b, op_b, diff)

    # Remaining unmatched = add/remove
    for k in range(pairs, len(remaining_sys)):
        i, b = remaining_sys[k]
        diff.block_changes.append(
            BlockChange(
                section_id=section_id,
                op="remove",
                block_index_before=i,
                title=b.title,
                block=b,
            )
        )
    for k in range(pairs, len(remaining_op)):
        i, b = remaining_op[k]
        diff.block_changes.append(
            BlockChange(
                section_id=section_id,
                op="add",
                block_index_after=i,
                title=b.title,
                block=b,
            )
        )


def _diff_single_block(
    section_id: str, idx: int, sys_b: DraftBlock, op_b: DraftBlock, diff: EditDiff
) -> None:
    if (sys_b.title or "") != (op_b.title or ""):
        diff.field_changes.append(
            FieldChange(
                section_id=section_id,
                block_index=idx,
                path="block.title",
                op="edit",
                before=sys_b.title,
                after=op_b.title,
            )
        )

    # Fields (by key)
    sys_fields = {f.key.lower(): f for f in sys_b.fields}
    op_fields = {f.key.lower(): f for f in op_b.fields}
    for k, op_f in op_fields.items():
        if k not in sys_fields:
            diff.field_changes.append(
                FieldChange(
                    section_id=section_id,
                    block_index=idx,
                    path=f"block.field:{op_f.key}",
                    op="add",
                    after=op_f.value,
                )
            )
        elif sys_fields[k].value != op_f.value:
            diff.field_changes.append(
                FieldChange(
                    section_id=section_id,
                    block_index=idx,
                    path=f"block.field:{op_f.key}",
                    op="edit",
                    before=sys_fields[k].value,
                    after=op_f.value,
                )
            )
    for k, sys_f in sys_fields.items():
        if k not in op_fields:
            diff.field_changes.append(
                FieldChange(
                    section_id=section_id,
                    block_index=idx,
                    path=f"block.field:{sys_f.key}",
                    op="remove",
                    before=sys_f.value,
                )
            )

    # Badges (set diff)
    sys_badges = set(sys_b.badges)
    op_badges = set(op_b.badges)
    for b in op_badges - sys_badges:
        diff.field_changes.append(
            FieldChange(
                section_id=section_id,
                block_index=idx,
                path=f"block.badge:{b}",
                op="add",
                after=b,
            )
        )
    for b in sys_badges - op_badges:
        diff.field_changes.append(
            FieldChange(
                section_id=section_id,
                block_index=idx,
                path=f"block.badge:{b}",
                op="remove",
                before=b,
            )
        )

    # Notes
    if (sys_b.notes or "") != (op_b.notes or ""):
        diff.field_changes.append(
            FieldChange(
                section_id=section_id,
                block_index=idx,
                path="block.notes",
                op="edit",
                before=sys_b.notes,
                after=op_b.notes,
            )
        )

    # Action items (as ordered list)
    sys_acts = set(sys_b.action_items)
    op_acts = set(op_b.action_items)
    for a in op_acts - sys_acts:
        diff.field_changes.append(
            FieldChange(
                section_id=section_id,
                block_index=idx,
                path="block.action_item",
                op="add",
                after=a,
            )
        )
    for a in sys_acts - op_acts:
        diff.field_changes.append(
            FieldChange(
                section_id=section_id,
                block_index=idx,
                path="block.action_item",
                op="remove",
                before=a,
            )
        )

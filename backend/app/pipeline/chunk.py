"""Structural chunking.

Splits a document into retrieval-sized chunks while preserving structure.
Rules:
  1. Primary split is on blank lines (paragraphs).
  2. Numbered items (`1.`, `2.`, ...) start new chunks — keeps each lien,
     each deadline, each court paragraph as its own retrievable unit.
  3. Very short paragraphs (< 40 chars) attach to the previous chunk to
     avoid useless fragments.
  4. Each chunk carries `line_start`, `line_end`, and a best-effort
     section header.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = ["ChunkData", "chunk_document"]


@dataclass
class ChunkData:
    text: str
    line_start: int
    line_end: int
    section_header: str | None = None


_NUMBERED_ITEM_RE = re.compile(r"^\s*(\d+)\.\s+(.+)$")
_LETTERED_HEADER_RE = re.compile(r"^\s*\(([a-zA-Z])\)\s+")


def _detect_header(lines: list[str]) -> str | None:
    """Best-effort section header from the first non-blank line of a chunk."""
    first = next((line.strip() for line in lines if line.strip()), "")
    if not first:
        return None

    m = _NUMBERED_ITEM_RE.match(first)
    if m:
        rest = m.group(2)
        # Grab the first clause before comma/period for a tight header.
        clause = re.split(r"[,.]", rest, maxsplit=1)[0]
        return f"{m.group(1)}. {clause[:60].strip()}"

    # An ALL CAPS line of a reasonable length is a heading.
    if first.isupper() and 3 <= len(first) <= 100:
        return first

    return None


def chunk_document(text: str, doc_type: str | None = None) -> list[ChunkData]:
    """Structurally chunk a document.

    `doc_type` is reserved for per-type tweaks later (e.g., email greeting
    skipping) but isn't used yet — structural rules handle our sample docs.
    """
    lines = text.splitlines()
    paragraphs: list[tuple[list[str], int, int]] = []  # (lines, start, end)
    current: list[str] = []
    start_line = 1

    for i, line in enumerate(lines, start=1):
        stripped = line.strip()

        # Blank line ends the current paragraph.
        if not stripped:
            if current:
                paragraphs.append((current, start_line, i - 1))
                current = []
            continue

        # If a non-empty line starts a numbered item AND we're already in a
        # paragraph, close the previous and start a new one so each item
        # stands alone.
        if current and _NUMBERED_ITEM_RE.match(line):
            paragraphs.append((current, start_line, i - 1))
            current = [line]
            start_line = i
            continue

        if not current:
            start_line = i
        current.append(line)

    if current:
        paragraphs.append((current, start_line, len(lines)))

    # Build ChunkData with detected headers. Blank-line boundaries are
    # respected strictly — no post-hoc merging — so the chunker is easy
    # to reason about.
    return [
        ChunkData(
            text="\n".join(para_lines).rstrip(),
            line_start=s,
            line_end=e,
            section_header=_detect_header(para_lines),
        )
        for para_lines, s, e in paragraphs
        if any(line.strip() for line in para_lines)
    ]

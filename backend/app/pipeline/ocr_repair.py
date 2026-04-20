"""Deterministic OCR-noise repair.

Focuses on the *safe* fixes where digit/letter confusion can be resolved
by context. Ambiguous cases (1 vs l vs I, inconsistently-cased words) are
left for the LLM extractor, which is strong at interpreting intent.

Safe fixes we apply here:
  1. `$445,OOO.OO`        →  `$445,000.00`   (O inside money)
  2. `2O21-O123456`       →  `2021-0123456`  (O inside dashed numeric tokens)
  3. `33-5O22-O14-O29O`   →  `33-5022-014-0290` (parcel numbers)
"""

from __future__ import annotations

import re

__all__ = ["RepairStats", "repair_ocr"]


class RepairStats(dict):
    """Statistics about OCR repairs performed on a document."""

    pass


_MONEY_RE = re.compile(r"\$[\d,O.]+")
_DASHED_NUMERIC_RE = re.compile(r"\b[\dO]{2,}(?:-[\dO]{2,}){1,}\b")


def repair_ocr(text: str) -> tuple[str, RepairStats]:
    """Apply deterministic OCR repairs. Returns (repaired_text, stats)."""
    stats = RepairStats(money_O_to_0=0, instrument_O_to_0=0, total_replacements=0)

    def money_sub(m: re.Match) -> str:
        orig = m.group(0)
        if "O" not in orig:
            return orig
        fixed = orig.replace("O", "0")
        stats["money_O_to_0"] += orig.count("O")
        stats["total_replacements"] += orig.count("O")
        return fixed

    def dashed_sub(m: re.Match) -> str:
        orig = m.group(0)
        if "O" not in orig:
            return orig
        # Must have at least one real digit — don't rewrite "O-O"
        if not any(c.isdigit() for c in orig):
            return orig
        fixed = orig.replace("O", "0")
        stats["instrument_O_to_0"] += orig.count("O")
        stats["total_replacements"] += orig.count("O")
        return fixed

    text = _MONEY_RE.sub(money_sub, text)
    text = _DASHED_NUMERIC_RE.sub(dashed_sub, text)
    return text, stats

"""Evaluation harness — produces the v1 vs v2 improvement table.

Six metrics, each designed to be:
  - Deterministic (or LLM-cached) so reruns are cheap.
  - Orthogonal (they measure different things).
  - Interpretable (a human can argue about what they mean).

Reporting target:

    | Metric                   | v1 (pre)  | v2 (post) |     Δ |
    |--------------------------|-----------|-----------|-------|
    | Grounded-claim coverage  | 0.6x      | 0.9x      | +0.3  |
    | Structural fidelity      | 0.5x      | 0.9x      | +0.4  |
    | Rule compliance          | 0.xx      | 0.9x      | +x    |
    | Citation accuracy        | 0.97      | 0.98      | +0.01 |
    | Hallucination rate       | 0.03      | 0.01      | -0.02 |
    | Avg latency (ms/section) | …         | …         |       |
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.tables import Case, Document, Draft, Pattern
from app.learning.patterns import active_patterns
from app.llm import client as llm
from app.models.draft import DraftContent
from app.models.enums import DraftType, LlmPurpose

DATA_DIR = Path("/app/data")


# --------------------------------------------------------------------------
# Fact extraction — deterministic, used for grounded-claim coverage
# --------------------------------------------------------------------------

_MONEY_RE = re.compile(r"\$[\d,]+(?:\.\d{1,2})?")
_INSTR_RE = re.compile(r"\b\d{4}-\d{7,}\b")
_ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_MDY_DATE_RE = re.compile(
    r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}\b"
)
_PARTY_RE = re.compile(
    r"\b(?:WELLS FARGO|NATIONSTAR|MR\.? COOPER|PALMETTO BAY|RODRIGUEZ|MENDEZ|NAVARRO|"
    r"THOMPSON|MERCADO|ROCKET MORTGAGE|CHASE)\b",
    re.IGNORECASE,
)


def extract_facts(text: str) -> set[str]:
    """Extract a normalized set of atomic facts from free-form text."""
    facts: set[str] = set()
    for m in _MONEY_RE.findall(text):
        facts.add("$" + m.lstrip("$").replace(",", ""))
    for m in _INSTR_RE.findall(text):
        facts.add(m)
    for m in _ISO_DATE_RE.findall(text):
        facts.add(m)
    for m in _MDY_DATE_RE.findall(text):
        facts.add(m.strip())
    for m in _PARTY_RE.findall(text):
        facts.add(m.upper())
    return facts


# --------------------------------------------------------------------------
# Metric 1: grounded-claim coverage
# --------------------------------------------------------------------------

def coverage(operator_text: str, draft_text: str) -> tuple[float, int, int]:
    """% of operator facts also present in the draft."""
    operator_facts = extract_facts(operator_text)
    draft_facts = extract_facts(draft_text)
    if not operator_facts:
        return 1.0, 0, 0
    found = len(operator_facts & draft_facts)
    return found / len(operator_facts), found, len(operator_facts)


# --------------------------------------------------------------------------
# Metric 2: structural fidelity
# --------------------------------------------------------------------------

_HEADING_RE = re.compile(r"^\s*(?:##+\s*|[A-Z][A-Z &]+$)", re.MULTILINE)


def _normalize_heading(h: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", h.strip().lower())


def _section_headings_from_markdown(md: str) -> set[str]:
    heads: set[str] = set()
    for line in md.splitlines():
        stripped = line.strip()
        if stripped.startswith("##"):
            heads.add(_normalize_heading(stripped.lstrip("#").strip()))
        elif stripped and stripped.isupper() and len(stripped) > 3 and len(stripped) < 80:
            heads.add(_normalize_heading(stripped))
    return {h for h in heads if h}


def structural_fidelity(operator_md: str, draft_md: str) -> tuple[float, int, int]:
    op_heads = _section_headings_from_markdown(operator_md)
    draft_heads = _section_headings_from_markdown(draft_md)
    if not op_heads:
        return 1.0, 0, 0
    matched = 0
    for op_h in op_heads:
        # Partial substring match — operator heading "LIENS & ENCUMBRANCES"
        # matches our draft "Liens and Encumbrances".
        if any(op_h in dh or dh in op_h for dh in draft_heads):
            matched += 1
    return matched / len(op_heads), matched, len(op_heads)


# --------------------------------------------------------------------------
# Metric 3: rule compliance (LLM, cached)
# --------------------------------------------------------------------------

class RuleCheck(BaseModel):
    pattern_id: int
    complied: bool
    reason: str = ""


class RuleComplianceResult(BaseModel):
    checks: list[RuleCheck]


_RULE_CHECK_PROMPT = """You check whether a generated draft complies with a
set of learned rules. For each rule, return complied=true/false and a
one-sentence reason. Be lenient on stylistic matters; be strict on
structural / factual rules (e.g., "every lien block must include instrument
number" — if any lien block is missing its instrument number, complied=false).
"""


async def rule_compliance(
    draft_md: str, rules: list[Pattern], *, case_id: int | None
) -> tuple[float, int, int]:
    if not rules:
        return 1.0, 0, 0
    if not llm.has_api_key():
        return 0.0, 0, len(rules)

    messages = [
        {"role": "system", "content": _RULE_CHECK_PROMPT},
        {
            "role": "user",
            "content": (
                "DRAFT:\n---\n"
                + draft_md
                + "\n---\n\nRULES:\n"
                + "\n".join(
                    f"[{p.id}] WHEN {p.rule_when} → MUST {p.rule_must}" for p in rules
                )
                + "\n\nReturn a RuleCheck per rule (preserve pattern_id)."
            ),
        },
    ]
    result = await llm.parse(
        purpose=LlmPurpose.verify,
        model=settings.model_cheap,
        messages=messages,
        response_format=RuleComplianceResult,
        case_id=case_id,
    )
    complied = sum(1 for c in result.checks if c.complied)
    total = len(result.checks) or len(rules)
    return complied / total, complied, total


# --------------------------------------------------------------------------
# Metric 4: citation accuracy
# --------------------------------------------------------------------------

async def citation_accuracy(
    draft: Draft, session: AsyncSession
) -> tuple[float, int, int]:
    """% of citations whose raw_text is found in the referenced source document."""
    content = DraftContent.model_validate(draft.content)
    # Build filename → text map for the case.
    docs = (
        (
            await session.execute(
                select(Document).where(Document.case_id == draft.case_id)
            )
        )
        .scalars()
        .all()
    )
    text_by_file = {d.filename: (d.raw_text + "\n" + (d.cleaned_text or "")) for d in docs}

    total = 0
    valid = 0
    for section in content.sections:
        for block in section.blocks:
            for cit in block.citations:
                for span in cit.spans:
                    total += 1
                    corpus = text_by_file.get(span.file, "")
                    if span.raw_text and span.raw_text.strip() in corpus:
                        valid += 1
                        continue
                    # Relaxed check: first 40 chars substring match
                    snippet = (span.raw_text or "").strip()[:40]
                    if snippet and snippet in corpus:
                        valid += 1
    if total == 0:
        return 1.0, 0, 0
    return valid / total, valid, total


# --------------------------------------------------------------------------
# Metric 5: hallucination rate (LLM verifier reuse)
# --------------------------------------------------------------------------

async def hallucination_rate(
    draft: Draft, session: AsyncSession
) -> tuple[float, int, int]:
    """Count the number of blocks that have zero citations — a proxy for
    hallucinated assertions. Deterministic and cheap."""
    content = DraftContent.model_validate(draft.content)
    total_blocks = 0
    unfounded = 0
    for section in content.sections:
        if section.abstained:
            continue
        for block in section.blocks:
            total_blocks += 1
            if not block.citations:
                unfounded += 1
    if total_blocks == 0:
        return 0.0, 0, 0
    return unfounded / total_blocks, unfounded, total_blocks


# --------------------------------------------------------------------------
# Operator version loaders
# --------------------------------------------------------------------------

def load_operator_version(draft_type: str) -> str:
    """Pull the operator-edited markdown from sample_edits.json."""
    path = DATA_DIR / "sample_edits.json"
    if not path.exists():
        return ""
    items = json.loads(path.read_text(encoding="utf-8"))
    for item in items:
        if item.get("draft_type") == draft_type:
            return item.get("operator_edited_version") or ""
    return ""


# --------------------------------------------------------------------------
# Top-level driver
# --------------------------------------------------------------------------


@dataclass
class DraftMetrics:
    draft_id: int
    draft_type: str
    template_version: int
    coverage: float
    coverage_counts: tuple[int, int]
    structural: float
    structural_counts: tuple[int, int]
    rule_compliance: float
    rule_counts: tuple[int, int]
    citation_accuracy: float
    citation_counts: tuple[int, int]
    hallucination_rate: float
    hallucination_counts: tuple[int, int]


@dataclass
class CompareRow:
    draft_type: str
    v1: DraftMetrics
    v2: DraftMetrics


@dataclass
class CaseEvalResult:
    case_id: int
    rows: list[CompareRow] = field(default_factory=list)


async def evaluate_draft(
    draft: Draft,
    operator_markdown: str,
    rules: list[Pattern],
    session: AsyncSession,
) -> DraftMetrics:
    cov, cov_found, cov_total = coverage(operator_markdown, draft.content_markdown)
    sf, sf_found, sf_total = structural_fidelity(operator_markdown, draft.content_markdown)
    rc, rc_ok, rc_total = await rule_compliance(
        draft.content_markdown, rules, case_id=draft.case_id
    )
    ca, ca_ok, ca_total = await citation_accuracy(draft, session)
    hr, hr_bad, hr_total = await hallucination_rate(draft, session)
    return DraftMetrics(
        draft_id=draft.id,
        draft_type=draft.draft_type,
        template_version=draft.template_version,
        coverage=cov,
        coverage_counts=(cov_found, cov_total),
        structural=sf,
        structural_counts=(sf_found, sf_total),
        rule_compliance=rc,
        rule_counts=(rc_ok, rc_total),
        citation_accuracy=ca,
        citation_counts=(ca_ok, ca_total),
        hallucination_rate=hr,
        hallucination_counts=(hr_bad, hr_total),
    )


async def evaluate_case(
    case_id: int,
    session: AsyncSession,
) -> CaseEvalResult:
    """Generate v1 (baseline) and v2 (patterns) for each draft type, then
    score them. Uses the diskcache layer so repeat runs are free."""
    from app.pipeline.generate import generate_draft  # local import avoids cycle

    case = await session.get(Case, case_id)
    if case is None:
        raise ValueError(f"Case {case_id} not found")

    result = CaseEvalResult(case_id=case_id)

    for draft_type in (DraftType.title_review_summary, DraftType.case_status_memo):
        operator_md = load_operator_version(draft_type.value)
        # Active rules used for BOTH v1 and v2 compliance measurement.
        rules = await active_patterns(session=session, draft_type=draft_type)

        v1 = await generate_draft(
            case_id=case_id,
            draft_type=draft_type,
            session=session,
            use_patterns=False,
        )
        v2 = await generate_draft(
            case_id=case_id,
            draft_type=draft_type,
            session=session,
            use_patterns=True,
        )

        v1_m = await evaluate_draft(v1, operator_md, rules, session)
        v2_m = await evaluate_draft(v2, operator_md, rules, session)
        result.rows.append(CompareRow(draft_type=draft_type.value, v1=v1_m, v2=v2_m))

    return result

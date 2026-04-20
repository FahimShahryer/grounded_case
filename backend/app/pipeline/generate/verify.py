"""Grounding verifier.

Two tiers:

1. **Deterministic** — cheap, always runs:
   - Every DraftBlock must have at least one Citation.
   - Every Citation must have at least one SourceSpan.
   - Every SourceSpan must reference a file that appears in the evidence pack.

2. **LLM spot-check** — one extra call (cached):
   - Extracts factual claims (numbers, dates, amounts, instrument numbers,
     proper nouns) from each block.
   - For each claim, checks whether the evidence pack contains it — either
     in `structured_facts` payloads or verbatim in `text_evidence`.
   - Returns unsupported claims so the generator can retry or hedge.

The deterministic pass covers the common case. The LLM pass catches
subtler hallucinations (e.g., an amount the LLM transposed digits on).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.config import settings
from app.db.tables import Pattern
from app.llm import client as llm
from app.models.draft import DraftSection
from app.models.enums import LlmPurpose
from app.models.evidence_pack import EvidencePack


class ClaimCheck(BaseModel):
    claim: str = Field(description="The factual claim being verified.")
    supported: bool
    reason: str = Field(
        default="",
        description="Why supported or not. 1 sentence.",
    )


class VerificationResult(BaseModel):
    claims: list[ClaimCheck] = Field(default_factory=list)
    all_supported: bool = True
    unsupported_claims: list[str] = Field(default_factory=list)
    rule_violations: list[str] = Field(default_factory=list)


# ------------------------------------------------------------------ deterministic


def verify_deterministic(section: DraftSection, evidence: EvidencePack) -> VerificationResult:
    issues: list[str] = []

    # Files the generator is allowed to cite (by filename, case-insensitive).
    allowed_files = {ec.filename.lower() for ec in evidence.text_evidence}
    for ef in evidence.structured_facts:
        for sp in ef.evidence_spans:
            allowed_files.add(sp.file.lower())

    if section.abstained:
        return VerificationResult(all_supported=True)

    for i, block in enumerate(section.blocks):
        label = block.title or f"block[{i}]"
        if not block.citations:
            issues.append(f"Block '{label}' has no citations.")
            continue
        for ci, cit in enumerate(block.citations):
            if not cit.spans:
                issues.append(f"Block '{label}' citation[{ci}] has no source spans.")
                continue
            for sp in cit.spans:
                if allowed_files and sp.file.lower() not in allowed_files:
                    issues.append(
                        f"Block '{label}' cites '{sp.file}' which is NOT in the "
                        f"evidence pack's allowed files {sorted(allowed_files)}."
                    )

    return VerificationResult(
        claims=[],
        all_supported=not issues,
        unsupported_claims=issues,
    )


# ------------------------------------------------------------------ LLM spot-check


_VERIFIER_PROMPT = """You are a grounding verifier. Given a generated draft
section and its evidence pack, you identify every factual claim in the
section (numbers, dates, amounts, instrument numbers, proper nouns) and
check whether each claim is supported by the evidence.

A claim is `supported=true` IF:
  - It matches a value in any `structured_facts[*].payload`, OR
  - It appears verbatim (or near-verbatim accounting for OCR noise like
    `$445,OOO.OO` → `$445,000.00`) in any `text_evidence[*].text`.

Otherwise `supported=false` and you must say why in one sentence.

Be strict about numbers and names — transposed digits, wrong dates, or
invented party names are all `supported=false`. Be lenient about style,
paraphrasing, and synthesis across facts.

Return ClaimCheck[] covering every factual claim. Set `all_supported`
based on whether any are false. Populate `unsupported_claims` with a
short description of each unsupported claim.

If a LEARNED_RULES list is provided in the user message, also check whether
the section complies with each rule. Populate `rule_violations` with a
short description of each violated rule. A violated rule flips
`all_supported` to false.
"""


async def verify_llm(
    section: DraftSection,
    evidence: EvidencePack,
    case_id: int | None = None,
    *,
    rules: list[Pattern] | None = None,
) -> VerificationResult:
    # Trim evidence for prompt size — we only need the payload + filename/line ranges.
    evidence_dump = {
        "structured_facts": [
            {
                "fact_type": f.fact_type,
                "payload": f.payload,
                "evidence_spans": [s.model_dump() for s in f.evidence_spans],
            }
            for f in evidence.structured_facts
        ],
        "text_evidence": [
            {
                "filename": e.filename,
                "line_start": e.line_start,
                "line_end": e.line_end,
                "text": e.text,
            }
            for e in evidence.text_evidence
        ],
        "known_gaps": evidence.known_gaps,
    }
    section_dump = section.model_dump(mode="json")

    rules_block = ""
    if rules:
        rules_block = "\nLEARNED_RULES:\n" + "\n".join(
            f"  - [{p.id}] WHEN {p.rule_when} → MUST {p.rule_must}" for p in rules
        )

    messages = [
        {"role": "system", "content": _VERIFIER_PROMPT},
        {
            "role": "user",
            "content": (
                "SECTION TO VERIFY:\n"
                f"{section_dump}\n\n"
                "EVIDENCE PACK:\n"
                f"{evidence_dump}\n"
                f"{rules_block}\n\n"
                "Return a VerificationResult."
            ),
        },
    ]
    result = await llm.parse(
        purpose=LlmPurpose.verify,
        model=settings.model_cheap,
        messages=messages,
        response_format=VerificationResult,
        case_id=case_id,
    )
    # Any rule violation forces all_supported=False.
    if result.rule_violations:
        result = result.model_copy(update={"all_supported": False})
    return result


# ------------------------------------------------------------------ composite


async def verify_section(
    section: DraftSection,
    evidence: EvidencePack,
    case_id: int | None = None,
    *,
    use_llm: bool = True,
    rules: list[Pattern] | None = None,
) -> VerificationResult:
    """Run deterministic checks first; if they pass, spot-check with the LLM."""
    det = verify_deterministic(section, evidence)
    if not det.all_supported:
        return det  # cheaper to fail fast

    if not use_llm or section.abstained or not llm.has_api_key():
        return det

    return await verify_llm(section, evidence, case_id=case_id, rules=rules)

"""Cross-document fact resolution — LLM-based semantic merge.

Given all per-document extractions for a case, a single LLM call reads
them together and returns canonical, deduplicated facts with evidence
citations back to the original documents.

Why LLM not regex:
  - Entity variations ("Wells Fargo Bank, N.A." / "WELLS FARGO BANK NA" /
    "Welss Fargo" typo) are a judgment call. Hand-written normalization
    has a maintenance ceiling; the model treats them as the same entity
    on context.
  - Partial-information merges ("the mortgage" in an email ↔ the
    full Wells Fargo mortgage record in the title search) need semantic
    understanding we can't fake with string matching.
  - Conflict surfacing is richer: the LLM can flag not just "different
    amounts" but "different terms for the same instrument".

Trade-offs, honestly surfaced:
  - Non-zero cost per /process run (~$0.005-0.015 with gpt-4.1-mini).
  - Non-deterministic on paper; in practice the prompt-hash diskcache
    pins identical inputs to identical outputs, so re-runs are free and
    stable.
  - Debuggability is worse than regex. We compensate with
    `dedup_key` = content-hash, so the same merged payload always
    maps to the same DB row across re-runs.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.tables import Document, Extraction, Fact, FactEvidence
from app.llm import client as llm
from app.models.enums import LlmPurpose
from app.models.fact import (
    CanonicalFactLLM,
    FactConflict,
    ResolverOutput,
)

log = logging.getLogger(__name__)

# ------------------------------------------------------------------ types


@dataclass
class ResolveResult:
    facts_created: int = 0
    facts_reused: int = 0
    evidence_created: int = 0
    conflicts: list[FactConflict] = field(default_factory=list)


# ------------------------------------------------------------------ prompt


_SYSTEM_PROMPT = """You are a legal-case fact resolver.

You will receive:
  1. The case metadata (case_number, borrower, property).
  2. A list of per-document extraction payloads. Each extraction came
     from one document (identified by `document_id`) and was produced
     by a doc-type-specific extractor (title_search, servicer_email,
     or court_order). Each fact inside an extraction already carries
     `source_spans` — the line numbers + verbatim text supporting it.

Your job is to MERGE these extractions into a canonical list of facts
about the case. One CanonicalFact per distinct real-world thing.

MERGING RULES

1. Two mentions across different documents are the SAME fact when they
   describe the same real-world object:
     - Same lien on the same property (same type + same creditor + same
       amount, or close variants). "Wells Fargo Bank, N.A." and
       "WELLS FARGO BANK NA" are the same entity. Corporate suffixes
       (LLC, Inc., N.A., L.P., d/b/a, etc.) are not distinguishing.
     - Same deadline (same ISO date, same event type).
     - Same transfer (same from_servicer → same to_servicer).
     - Same action_item (same request, even if phrased differently).
     - Same tax year for the same parcel.
2. When merging, produce ONE payload combining the most complete
   information from all sources. Prefer the value with higher confidence;
   if missing in one source, take it from another.
3. Preserve the full evidence trail. Every source document that mentioned
   this fact must appear in `evidence[]` with its document_id and the
   exact source_span (line_start / line_end / raw_text).
4. Do NOT invent facts that aren't in any extraction. Every fact in your
   output must trace to at least one source_span from the input.
5. If two sources agree on identity (same type + same entity) but
   DISAGREE on a material field (e.g. two different amounts for the same
   mortgage, two different payoff totals) → set `conflict: true` and
   explain in `conflict_note`. Still emit ONE canonical fact; the
   conflict flag tells downstream callers to hedge.

FACT TYPES — map each extraction's nested items to these:
  - `liens` → fact_type="lien"
  - `tax_statuses` → fact_type="tax"
  - `chain_of_title` → fact_type="ownership"
  - `payoff_update` → fact_type="payoff"
  - `transfer` → fact_type="transfer"
  - `attorney` → fact_type="attorney"
  - `action_items` → fact_type="action_item"
  - `deadlines` → fact_type="deadline"
  - `required_appearances` → fact_type="appearance"
  - `filing_requirements` → fact_type="filing_requirement"

DEDUP HINT
Each fact needs a short human-readable `dedup_hint` string — just used
to make re-runs stable. Keep it short, lowercase, descriptive:
  "mortgage-wells-fargo-445k"
  "hoa-lis-pendens-palmetto-bay-3420"
  "deadline-2026-04-15-proof-of-service"
  "payoff-2026-03-01"

PAYLOAD SHAPE
`payload` is free-form but should mirror the source extraction's shape
for that fact type (so downstream draft generation can read it). Copy
the merged fields; don't rename them. Do NOT include `source_spans` in
the payload — evidence is captured separately in the `evidence[]` array.

TEMPORAL HANDLING (important)
Legal cases change over time — later emails supersede earlier ones.
When the SAME identity-fact appears in multiple sources with different
timestamps, treat the MOST RECENT source as canonical:

  - Timestamp priority: field-level date (e.g. `payoff_update.as_of`,
    `transfer.effective_date`, `action_item.deadline`) first; if absent,
    fall back to the containing extraction's `received_date` (emails)
    or the document's position in the extraction list (later = newer
    if dates tie).
  - The canonical `payload` gets the LATEST value's fields.
  - Add a `previous_values` array to the payload listing each
    superseded version in ascending order, each an object with the
    old field(s) + the `as_of` (or best-available) date. Example:
      {
        "amount": "490500.00",
        "as_of": "2026-03-20",
        "previous_values": [
          {"amount": "487920.00", "as_of": "2026-03-15"}
        ]
      }
  - Evidence spans for BOTH the current and superseded values must
    appear in the `evidence[]` array so the operator can click through
    to either.
  - If two sources have the same timestamp and disagree, that's a real
    `conflict` — flag it (conflict=true) and explain in conflict_note.

Applies to: payoff, transfer effective dates, action_items that got
re-issued, any fact that can legitimately change over time.

Does NOT apply to: static facts (property address, legal description,
existing lien instruments). For those, merge as before — take the most
complete fields across sources.
"""


# ------------------------------------------------------------------ helpers


def _canonical_payload_hash(fact_type: str, payload: dict) -> str:
    """Stable 32-char hex hash of (fact_type, payload). Used as dedup_key.

    JSON-canonicalised with sorted keys so two semantically identical
    payloads produce the same hash regardless of key ordering.
    """
    data = json.dumps(
        {"fact_type": fact_type, "payload": payload},
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
    return hashlib.sha256(data.encode("utf-8")).hexdigest()[:32]


def _strip_null_bytes(s: str) -> str:
    """Postgres JSONB rejects `\\u0000` in strings. LLMs occasionally emit
    malformed Unicode escapes (e.g. `\\u0000a7` intending `§`) that survive
    JSON parsing but crash the asyncpg driver on insert. Strip them."""
    return s.replace("\x00", "") if s else s


def _sanitize_payload(obj):
    """Recursively strip NUL bytes from every string in a nested structure."""
    if isinstance(obj, str):
        return _strip_null_bytes(obj)
    if isinstance(obj, dict):
        return {k: _sanitize_payload(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_payload(v) for v in obj]
    return obj


def _build_user_message(
    *, case_number: str, borrower: str, doc_extractions: list[tuple[Document, Extraction]]
) -> str:
    parts: list[str] = [
        "CASE:",
        f"  case_number: {case_number}",
        f"  borrower: {borrower}",
        "",
        f"EXTRACTIONS ({len(doc_extractions)}):",
    ]
    for doc, ext in doc_extractions:
        parts.append("")
        parts.append(f"--- document_id={doc.id}  filename={doc.filename}  type={ext.extractor_type} ---")
        parts.append(json.dumps(ext.payload, indent=2, default=str))
    parts.append("")
    parts.append(
        "Return ResolverOutput with one CanonicalFact per distinct real-world "
        "fact. Preserve all evidence spans. Flag material conflicts."
    )
    return "\n".join(parts)


# ------------------------------------------------------------------ public API


async def resolve_facts(case_id: int, session: AsyncSession) -> ResolveResult:
    """Merge all per-document extractions for a case into canonical facts.

    Idempotent: a re-run with identical extractions hits the LLM cache,
    produces the same output, and content-hash dedup_keys guarantee the
    same `facts` rows are updated (not duplicated).
    """
    # Load case + all extractions in order.
    from app.db.tables import Case  # lazy to avoid cycles

    case = await session.get(Case, case_id)
    if case is None:
        return ResolveResult()

    rows = (
        await session.execute(
            select(Extraction, Document)
            .join(Document, Document.id == Extraction.document_id)
            .where(Document.case_id == case_id)
            .order_by(Document.id)
        )
    ).all()

    doc_extractions = [(doc, ext) for ext, doc in rows]

    if not doc_extractions:
        return ResolveResult()

    # Call the LLM. On cache hit this is free + instant.
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": _build_user_message(
                case_number=case.case_number,
                borrower=case.borrower,
                doc_extractions=doc_extractions,
            ),
        },
    ]

    try:
        output: ResolverOutput = await llm.parse(
            purpose=LlmPurpose.resolve,
            model=settings.model_cheap,  # gpt-4.1-mini is plenty for structured merge
            messages=messages,
            response_format=ResolverOutput,
            case_id=case_id,
        )
    except Exception as e:
        log.exception("Resolver LLM call failed for case %d: %s", case_id, e)
        raise

    # Valid document_ids we can attach evidence to (sanity-check LLM output).
    valid_doc_ids = {doc.id for doc, _ in doc_extractions}

    return await _persist_resolver_output(
        case_id=case_id,
        session=session,
        canonical_facts=output.facts,
        valid_doc_ids=valid_doc_ids,
    )


async def _persist_resolver_output(
    *,
    case_id: int,
    session: AsyncSession,
    canonical_facts: list[CanonicalFactLLM],
    valid_doc_ids: set[int],
) -> ResolveResult:
    result = ResolveResult()

    for cf in canonical_facts:
        if not cf.evidence:
            log.warning(
                "Resolver emitted a fact with no evidence (case=%d type=%s hint=%r); skipping",
                case_id,
                cf.fact_type,
                cf.dedup_hint,
            )
            continue

        # Parse the JSON-encoded payload. Malformed output = skip, not crash.
        try:
            payload = json.loads(cf.payload_json)
            if not isinstance(payload, dict):
                raise ValueError("payload must be a JSON object")
            payload = _sanitize_payload(payload)
        except (ValueError, json.JSONDecodeError) as e:
            log.warning(
                "Resolver payload_json invalid (case=%d type=%s hint=%r): %s; skipping",
                case_id,
                cf.fact_type,
                cf.dedup_hint,
                e,
            )
            continue

        dedup_key = _canonical_payload_hash(cf.fact_type, payload)

        # Upsert the Fact row.
        existing = (
            await session.execute(
                select(Fact).where(
                    Fact.case_id == case_id,
                    Fact.fact_type == cf.fact_type,
                    Fact.dedup_key == dedup_key,
                )
            )
        ).scalar_one_or_none()

        if existing is None:
            fact = Fact(
                case_id=case_id,
                fact_type=cf.fact_type,
                dedup_key=dedup_key,
                payload=payload,
                confidence=max((e.confidence for e in cf.evidence), default=1.0),
            )
            session.add(fact)
            await session.flush()
            result.facts_created += 1
        else:
            existing.payload = payload
            fact = existing
            result.facts_reused += 1

        if cf.conflict:
            result.conflicts.append(
                FactConflict(
                    dedup_key=dedup_key,
                    fact_type=cf.fact_type,
                    candidates=[{"payload": payload, "note": cf.conflict_note or ""}],
                )
            )

        # Attach evidence — skip rows the LLM invented (unknown document_id)
        # and dedup against any existing evidence on this fact.
        existing_ev_rows = (
            await session.execute(
                select(FactEvidence).where(FactEvidence.fact_id == fact.id)
            )
        ).scalars().all()
        seen = {
            (e.document_id, e.span.get("line_start"), e.span.get("line_end"))
            for e in existing_ev_rows
        }

        for ev in cf.evidence:
            if ev.document_id not in valid_doc_ids:
                log.warning(
                    "Resolver cited unknown document_id=%d on fact %d; skipping span",
                    ev.document_id,
                    fact.id,
                )
                continue
            span = {
                "file": "",  # filename is derivable via document_id — keep empty for consistency
                "line_start": ev.line_start,
                "line_end": ev.line_end,
                "raw_text": _strip_null_bytes(ev.raw_text),
                "confidence": ev.confidence,
            }
            # Backfill the filename from the document for consistency with extractor-produced spans.
            # The downstream viewer uses `span.file` for the highlighting, so we populate it.
            doc = await session.get(Document, ev.document_id)
            if doc is not None:
                span["file"] = doc.filename

            key = (ev.document_id, ev.line_start, ev.line_end)
            if key in seen:
                continue
            session.add(
                FactEvidence(fact_id=fact.id, document_id=ev.document_id, span=span)
            )
            seen.add(key)
            result.evidence_created += 1

    await session.commit()
    return result

"""Evidence pack assembly.

For each `SectionQuery` we:
  1. Pull canonical facts of the requested `fact_types` from the graph.
  2. Run multi-angle hybrid retrieval, dedup by chunk_id, filter by
     `doc_type`, then LLM-rerank the top candidates to a tight top_k.
  3. Record explicit gaps when structured facts are empty for a section
     that asserts presence.
  4. Attach conflicts surfaced by the resolver for the same fact types.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.tables import Document, Fact, FactEvidence
from app.models.common import SourceSpan
from app.models.evidence_pack import EvidenceChunk, EvidenceFact, EvidencePack
from app.models.fact import FactConflict
from app.pipeline.plans import SectionQuery
from app.pipeline.rerank import rerank
from app.pipeline.retrieve import SearchHit, hybrid_search

_MAX_TEXT_HITS = 5
_RERANK_POOL = 20


async def _load_structured_facts(
    case_id: int, fact_types: list[str], session: AsyncSession
) -> tuple[list[EvidenceFact], list[FactConflict]]:
    if not fact_types:
        return [], []

    facts = (
        (
            await session.execute(
                select(Fact)
                .where(Fact.case_id == case_id, Fact.fact_type.in_(fact_types))
                .order_by(Fact.fact_type, Fact.id)
            )
        )
        .scalars()
        .all()
    )

    out_facts: list[EvidenceFact] = []
    if facts:
        fact_ids = [f.id for f in facts]
        ev_rows = (
            (
                await session.execute(
                    select(FactEvidence).where(FactEvidence.fact_id.in_(fact_ids))
                )
            )
            .scalars()
            .all()
        )
        by_fact: dict[int, list[SourceSpan]] = {}
        for ev in ev_rows:
            try:
                by_fact.setdefault(ev.fact_id, []).append(SourceSpan(**ev.span))
            except Exception:
                continue

        for f in facts:
            out_facts.append(
                EvidenceFact(
                    fact_id=f.id,
                    fact_type=f.fact_type,
                    dedup_key=f.dedup_key,
                    payload=f.payload,
                    confidence=float(f.confidence),
                    evidence_spans=by_fact.get(f.id, []),
                )
            )

    # Conflicts: same fact_type + >1 row sharing dedup_key would be
    # returned by the resolver; at read-time we re-detect by inspecting
    # payloads grouped by (fact_type, dedup_key).
    conflicts: list[FactConflict] = []
    grouped: dict[tuple[str, str], list[Fact]] = {}
    for f in facts:
        grouped.setdefault((f.fact_type, f.dedup_key), []).append(f)
    for (ft, key), group in grouped.items():
        if len(group) > 1:
            conflicts.append(
                FactConflict(dedup_key=key, fact_type=ft, candidates=[x.payload for x in group])
            )

    return out_facts, conflicts


async def _retrieve_chunks_for_section(
    case_id: int, section: SectionQuery, session: AsyncSession
) -> list[SearchHit]:
    """Run each query angle, merge by chunk id (max score wins), filter, trim."""
    by_id: dict[int, SearchHit] = {}

    for query in section.queries:
        hits = await hybrid_search(case_id, query, session=session, top_k=_RERANK_POOL)
        for h in hits:
            if h.chunk is None:
                continue
            if section.doc_type_filter and h.chunk.doc_type not in section.doc_type_filter:
                continue
            # Keep the highest-scoring variant of each chunk across queries.
            existing = by_id.get(h.chunk_id)
            if existing is None or h.score > existing.score:
                by_id[h.chunk_id] = h

    # Sort by score, take top of pool to feed rerank.
    pool = sorted(by_id.values(), key=lambda h: h.score, reverse=True)[:_RERANK_POOL]

    # Rerank with LLM to tighten precision to top_k.
    reranked = await rerank(
        query=section.description,
        hits=pool,
        top_k=_MAX_TEXT_HITS,
        case_id=case_id,
    )
    return reranked


async def _chunks_to_evidence(
    hits: list[SearchHit], session: AsyncSession
) -> list[EvidenceChunk]:
    if not hits:
        return []

    doc_ids = {h.chunk.document_id for h in hits if h.chunk is not None}
    docs = (
        (await session.execute(select(Document).where(Document.id.in_(doc_ids))))
        .scalars()
        .all()
    )
    filename_by_doc = {d.id: d.filename for d in docs}

    out: list[EvidenceChunk] = []
    for h in hits:
        if h.chunk is None:
            continue
        out.append(
            EvidenceChunk(
                chunk_id=h.chunk_id,
                document_id=h.chunk.document_id,
                filename=filename_by_doc.get(h.chunk.document_id, ""),
                doc_type=h.chunk.doc_type,
                line_start=h.chunk.line_start,
                line_end=h.chunk.line_end,
                section_header=h.chunk.section_header,
                text=h.chunk.text,
                score=h.score,
                ranks=h.ranks,
            )
        )
    return out


async def build_evidence_pack(
    case_id: int, section: SectionQuery, session: AsyncSession
) -> EvidencePack:
    structured_facts, conflicts = await _load_structured_facts(
        case_id, section.fact_types, session
    )
    text_hits = await _retrieve_chunks_for_section(case_id, section, session)
    text_evidence = await _chunks_to_evidence(text_hits, session)

    gaps: list[str] = []
    if section.assert_presence and section.fact_types and not structured_facts:
        gaps.append(
            f"No {' / '.join(section.fact_types)} facts found in case graph "
            f"for section '{section.section_id}'."
        )
    if not text_evidence and not structured_facts:
        gaps.append(
            f"No evidence retrieved for '{section.description}'. "
            f"Source materials may not address this topic."
        )

    return EvidencePack(
        section_id=section.section_id,
        description=section.description,
        structured_facts=structured_facts,
        text_evidence=text_evidence,
        known_gaps=gaps,
        conflicts=conflicts,
    )

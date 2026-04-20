"""Evidence pack endpoint.

Returns the grounded evidence bundle for a specific section of a specific
draft type. This is what Step 7's generator consumes.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import SessionDep
from app.db.tables import Case
from app.models.enums import DraftType
from app.models.evidence_pack import EvidencePack
from app.pipeline.evidence import build_evidence_pack
from app.pipeline.plans import PLANS, plan_for

DraftTypeQuery = Annotated[
    DraftType,
    Query(description="Which draft plan's sections to resolve `section_id` against."),
]

router = APIRouter(prefix="/api/cases/{case_id}", tags=["evidence"])


@router.get("/evidence/{section_id}", response_model=EvidencePack)
async def get_evidence(
    case_id: int,
    section_id: str,
    session: SessionDep,
    draft_type: DraftTypeQuery = DraftType.title_review_summary,
) -> EvidencePack:
    case = await session.get(Case, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    plan = plan_for(draft_type)
    section = next((s for s in plan.sections if s.section_id == section_id), None)
    if section is None:
        known = [s.section_id for s in plan.sections]
        raise HTTPException(
            status_code=404,
            detail=(
                f"Unknown section_id '{section_id}' for draft_type={draft_type}. "
                f"Known sections: {known}"
            ),
        )

    return await build_evidence_pack(case_id, section, session)


@router.get("/plans")
async def list_plans() -> dict:
    """Debug helper: list all draft plans and their sections."""
    return {
        draft_type.value: {
            "sections": [
                {
                    "section_id": s.section_id,
                    "description": s.description,
                    "doc_type_filter": s.doc_type_filter,
                    "fact_types": s.fact_types,
                }
                for s in plan.sections
            ]
        }
        for draft_type, plan in PLANS.items()
    }

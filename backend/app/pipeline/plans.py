"""Query plans per draft type.

A plan says: *these* are the sections that belong in this draft, and for
each one, *these* are the retrieval angles + which fact types in the graph
apply. Keeps the generator declarative — new draft type = new plan, no
retrieval code changes.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.enums import DraftType


class SectionQuery(BaseModel):
    section_id: str
    description: str  # one-sentence human description; also used as rerank query
    queries: list[str] = Field(
        description="Multiple retrieval angles fused into one evidence pack."
    )
    doc_type_filter: list[str] | None = None
    fact_types: list[str] = Field(
        default_factory=list,
        description="Fact types to pull from the knowledge graph for this section.",
    )
    # When true and no structured facts are found, an explicit 'absence' gap
    # is added so the generator can assert 'none found in source materials'
    # instead of guessing.
    assert_presence: bool = True


class DraftPlan(BaseModel):
    draft_type: DraftType
    sections: list[SectionQuery]


# ---------------------------------------------------------------- plans ---


TITLE_REVIEW_PLAN = DraftPlan(
    draft_type=DraftType.title_review_summary,
    sections=[
        SectionQuery(
            section_id="liens",
            description="Liens and encumbrances on the property",
            queries=[
                "mortgage liens and encumbrances",
                "HOA lis pendens",
                "assignment of mortgage",
                "easements and restrictive covenants",
            ],
            doc_type_filter=["title_search"],
            fact_types=["lien"],
        ),
        SectionQuery(
            section_id="tax_status",
            description="Property tax status (paid/unpaid, year, amount)",
            queries=[
                "property taxes paid or unpaid",
                "tax parcel and delinquent taxes",
                "special assessments",
            ],
            doc_type_filter=["title_search"],
            fact_types=["tax"],
        ),
        SectionQuery(
            section_id="ownership",
            description="Chain of ownership and current vesting",
            queries=[
                "chain of title conveyances",
                "current vesting and prior owner",
                "warranty deed",
            ],
            doc_type_filter=["title_search"],
            fact_types=["ownership"],
        ),
        SectionQuery(
            section_id="judgments",
            description="Outstanding judgments and federal/state tax liens against borrower",
            queries=[
                "unsatisfied judgments against borrower",
                "federal tax liens",
                "state tax liens",
            ],
            doc_type_filter=["title_search"],
            fact_types=["judgment"],  # none in our sample → triggers gap
        ),
    ],
)


CASE_STATUS_PLAN = DraftPlan(
    draft_type=DraftType.case_status_memo,
    sections=[
        SectionQuery(
            section_id="action_items",
            description="Action items and urgent tasks from servicer and court",
            queries=[
                "action items to do",
                "urgent tasks",
                "please file or submit",
            ],
            fact_types=["action_item"],
        ),
        SectionQuery(
            section_id="deadlines",
            description="Upcoming deadlines, filing requirements, and hearings",
            queries=[
                "upcoming deadlines",
                "case management report due",
                "proof of service deadline",
                "case management conference",
            ],
            fact_types=["deadline", "filing_requirement", "appearance"],
        ),
        SectionQuery(
            section_id="payoff",
            description="Current payoff amount and effective date",
            queries=["payoff amount", "loan payoff as of date"],
            doc_type_filter=["servicer_email"],
            fact_types=["payoff"],
        ),
        SectionQuery(
            section_id="servicing",
            description="Servicing transfer and borrower's counsel",
            queries=[
                "servicing transfer to Mr. Cooper",
                "borrower retained counsel",
                "attorney representation",
            ],
            doc_type_filter=["servicer_email"],
            fact_types=["transfer", "attorney"],
        ),
        SectionQuery(
            section_id="title_concerns",
            description="Title concerns relevant to case posture",
            queries=[
                "HOA lis pendens",
                "delinquent property taxes",
                "assignment chain",
            ],
            doc_type_filter=["title_search"],
            fact_types=["lien", "tax"],
        ),
    ],
)


PLANS: dict[DraftType, DraftPlan] = {
    DraftType.title_review_summary: TITLE_REVIEW_PLAN,
    DraftType.case_status_memo: CASE_STATUS_PLAN,
}


def plan_for(draft_type: DraftType) -> DraftPlan:
    if draft_type not in PLANS:
        raise KeyError(f"No query plan defined for draft_type={draft_type}")
    return PLANS[draft_type]

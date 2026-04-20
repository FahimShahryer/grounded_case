"""Per-section prose guidance for the section generator.

These short strings nudge the LLM toward the structure an operator
expects for each section — e.g., "one block per lien", "flag HOA lis
pendens with ACTION REQUIRED badge", "include instrument numbers".

This is intentionally thin — structural learning happens via the
pattern store in Step 9. These defaults are the pre-learning baseline.
"""

from app.models.enums import DraftType

# Keyed by (draft_type.value, section_id)
GUIDANCE: dict[tuple[str, str], str] = {
    # --- Title Review Summary ---
    ("title_review_summary", "liens"): (
        "Produce one DraftBlock per distinct lien or encumbrance. "
        "Each block's title should identify the lien (e.g., 'First Mortgage — Wells Fargo'). "
        "Include FieldLine rows for: Original Amount, Date Recorded, Instrument No., Status. "
        "Use badges like 'ASSIGNED' when a mortgage has been assigned. "
        "Prefer structured_facts for precise values; use text_evidence for raw supporting language."
    ),
    ("title_review_summary", "tax_status"): (
        "One block per tax year. Include FieldLine rows for: Year, Amount, Paid/Unpaid, Due Date, "
        "Tax Parcel. Highlight delinquent years with an 'DELINQUENT' badge."
    ),
    ("title_review_summary", "ownership"): (
        "One block per conveyance in the chain of title. Latest vesting goes last. "
        "Include grantor, grantee, instrument type, recording date, and instrument number."
    ),
    ("title_review_summary", "judgments"): (
        "If no judgments are in structured_facts, write a single short body sentence like "
        "'No unsatisfied judgments or tax liens identified in source materials.' — cite the "
        "text evidence that explicitly says so if it exists. Do not invent judgments."
    ),
    # --- Case Status Memo ---
    ("case_status_memo", "action_items"): (
        "One block per action item. Title should be a 2-6 word imperative ('File proof of service'). "
        "Use a badge for priority: 'URGENT', 'HIGH', 'NORMAL', 'LOW'. "
        "Include FieldLine rows for Deadline (if any) and Owner."
    ),
    ("case_status_memo", "deadlines"): (
        "One block per deadline / hearing / filing requirement, ordered chronologically. "
        "Block title: the event (e.g., 'Case Management Conference'). "
        "Fields: Date, Required Action, What Must Happen By Then."
    ),
    ("case_status_memo", "payoff"): (
        "One block. Fields: Amount, As Of Date, Source (the servicer email). "
        "If multiple payoffs conflict, surface both with a 'CONFLICT' badge."
    ),
    ("case_status_memo", "servicing"): (
        "Two blocks: one for the active servicing transfer (from/to/effective_date), "
        "one for borrower's counsel (name/firm/phone). "
        "Add 'ACTIVE TRANSFER' badge to the transfer block."
    ),
    ("case_status_memo", "title_concerns"): (
        "Brief one-line-per-concern blocks pulling from lien/tax structured facts. "
        "Emphasize HOA lis pendens (party-naming decision) and delinquent taxes."
    ),
}


def guidance_for(draft_type: DraftType, section_id: str) -> str:
    return GUIDANCE.get((draft_type.value, section_id), "")

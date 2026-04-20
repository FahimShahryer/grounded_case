"""Document-type classification.

Goes through the LLM when an API key is configured; otherwise falls back
to a deterministic rule (filename match) so the pipeline stays testable
without network/API access.
"""

from pydantic import BaseModel, Field

from app.config import settings
from app.llm import client as llm
from app.models.enums import DocType, LlmPurpose

_SYSTEM_PROMPT = """You classify legal case management documents.
Possible categories:
  - title_search: Schedule B title exceptions, legal descriptions, tax/judgment searches
  - servicer_email: Email from a loan servicer with operational instructions
  - court_order: Formal court order setting deadlines, hearings, or appearances
  - property_record: Property ownership, conveyance, or tax record
  - other: Anything that does not fit the above

Read the text and return ONLY a single doc_type value.
"""


class Classification(BaseModel):
    doc_type: DocType = Field(description="The classified document type.")
    rationale: str = Field(
        default="",
        description="One short sentence justifying the classification.",
    )


def _rule_based_classify(filename: str, text: str) -> Classification:
    """Deterministic fallback when OPENAI_API_KEY is not set.

    Used only for dev / CI without API access. In production this is a
    safety net — the LLM path is the primary one.
    """
    name = (filename or "").lower()
    head = (text or "")[:1000].lower()

    if "title_search" in name or "schedule b" in head or "title search" in head:
        return Classification(doc_type=DocType.title_search, rationale="filename/header match")
    if "servicer_email" in name or "email" in name or "from:" in head:
        return Classification(doc_type=DocType.servicer_email, rationale="filename/header match")
    if "court_order" in name or "order" in name or "case management" in head:
        return Classification(doc_type=DocType.court_order, rationale="filename/header match")
    if "property" in name or "parcel" in head:
        return Classification(doc_type=DocType.property_record, rationale="filename/header match")
    return Classification(doc_type=DocType.other, rationale="no rule matched")


async def classify_document(
    *,
    text: str,
    filename: str | None = None,
    case_id: int | None = None,
) -> Classification:
    """Classify a document; use the LLM when available, otherwise rules."""
    if not llm.has_api_key():
        return _rule_based_classify(filename or "", text)

    # Truncate to keep the classifier cheap — doc type is obvious from the head.
    excerpt = text[:4000]
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Filename: {filename or '(unknown)'}\n\n"
                f"Document excerpt (first 4000 chars):\n---\n{excerpt}\n---"
            ),
        },
    ]

    return await llm.parse(
        purpose=LlmPurpose.classify,
        model=settings.model_cheap,
        messages=messages,
        response_format=Classification,
        case_id=case_id,
    )

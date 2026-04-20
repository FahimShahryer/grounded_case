"""Common helpers for per-doc-type extractors.

Every extractor follows the same shape:
  1. Prefix source lines with `[L{n}]` so the LLM can cite by line.
  2. Call the LLM with a per-doc-type system prompt and a typed response
     schema; parse returns a typed Pydantic object.
  3. Convert the LLM-facing object (str dates/amounts) into the canonical
     typed schema (Decimal, date) via per-extractor converters.
  4. Return an ExtractorResult carrying the canonical payload dict plus
     metadata.

Using LLM-facing schemas with str fields (not Decimal/date) keeps us
compatible with OpenAI's strict JSON-schema mode, which rejects
`format: "date"` and coerces Decimal handling inconsistently across
models.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, Field

from app.config import settings
from app.llm import client as llm
from app.models.enums import LlmPurpose

__all__ = [
    "ExtractorResult",
    "number_lines",
    "parse_date",
    "parse_decimal",
    "run_extractor",
]


# ------------------------------------------------------------------ helpers


def number_lines(text: str) -> str:
    """Prefix every line with `[L{n}]` for unambiguous LLM citations."""
    return "\n".join(f"[L{i + 1}] {line}" for i, line in enumerate(text.splitlines()))


def parse_decimal(s: str | None) -> Decimal | None:
    if s is None:
        return None
    cleaned = s.strip().replace("$", "").replace(",", "")
    if not cleaned:
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def parse_date(s: str | None) -> date | None:
    if s is None:
        return None
    s = s.strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%B %d, %Y", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


# ------------------------------------------------------------------ models


class ExtractorResult(BaseModel):
    """Envelope returned by any extractor: the typed canonical payload + meta."""

    extractor_type: str
    extractor_version: str
    payload: dict = Field(description="The canonical extraction serialized.")
    confidence: float = 1.0


# ------------------------------------------------------------------ runner


async def run_extractor(
    *,
    system_prompt: str,
    text: str,
    filename: str,
    response_model: type[BaseModel],
    case_id: int | None = None,
    model: str | None = None,
) -> BaseModel:
    """Invoke the LLM with numbered source lines; return the parsed model."""
    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                f"File: {filename}\n\n"
                f"{number_lines(text)}"
            ),
        },
    ]
    return await llm.parse(
        purpose=LlmPurpose.extract,
        model=model or settings.model_primary,
        messages=messages,
        response_format=response_model,
        case_id=case_id,
    )


async def extract_document(  # pragma: no cover -- dispatcher wired in Step 4 orchestrator
    *,
    doc_type: str,
    text: str,
    filename: str,
    case_id: int | None = None,
) -> ExtractorResult:
    """Dispatch to the right extractor by doc_type."""
    # Lazy imports to avoid circular module load.
    from app.pipeline.extract.court_order import extract_court_order
    from app.pipeline.extract.servicer_email import extract_servicer_email
    from app.pipeline.extract.title_search import extract_title_search

    if doc_type == "title_search":
        return await extract_title_search(text=text, filename=filename, case_id=case_id)
    if doc_type == "servicer_email":
        return await extract_servicer_email(text=text, filename=filename, case_id=case_id)
    if doc_type == "court_order":
        return await extract_court_order(text=text, filename=filename, case_id=case_id)

    # Unknown doc types produce an empty extraction rather than crashing the pipeline.
    return ExtractorResult(
        extractor_type=doc_type,
        extractor_version="v0",
        payload={"note": "no extractor configured for this doc_type"},
        confidence=0.0,
    )

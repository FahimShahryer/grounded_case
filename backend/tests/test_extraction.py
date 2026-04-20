"""Integration tests for the extraction pipeline.

These call the real LLM. First run costs ~$0.05 in total; the
diskcache layer makes every subsequent run free. If OPENAI_API_KEY is
not configured, these tests are skipped.

Golden assertions target the well-known Rodriguez sample documents.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from app.llm.client import has_api_key
from app.pipeline.extract.court_order import extract_court_order
from app.pipeline.extract.servicer_email import extract_servicer_email
from app.pipeline.extract.title_search import extract_title_search
from app.pipeline.ocr_repair import repair_ocr

DATA = Path("/app/data/rodriguez/sample_documents")


pytestmark = pytest.mark.skipif(
    not has_api_key(), reason="OPENAI_API_KEY not set; skipping LLM extraction tests"
)


def _load(name: str) -> str:
    raw = (DATA / name).read_text(encoding="utf-8")
    cleaned, _ = repair_ocr(raw)
    return cleaned


async def test_title_search_extracts_all_liens():
    text = _load("title_search_page1.txt")
    result = await extract_title_search(
        text=text, filename="title_search_page1.txt", case_id=None
    )
    payload = result.payload
    liens = payload["liens"]

    # Expect at least 3 distinct liens: mortgage, assignment, HOA lis pendens
    lien_types = {lien["lien_type"] for lien in liens}
    assert "mortgage" in lien_types
    assert "assignment" in lien_types
    assert "hoa_lis_pendens" in lien_types

    mortgage = next(lien for lien in liens if lien["lien_type"] == "mortgage")
    assert mortgage["instrument_number"] == "2021-0123456"
    assert Decimal(str(mortgage["amount"])) == Decimal("445000.00")

    # Every lien has at least one source span pointing back to the file.
    for lien in liens:
        assert lien["source_spans"], f"lien has no citations: {lien}"
        span = lien["source_spans"][0]
        assert span["file"] == "title_search_page1.txt"
        assert span["line_start"] >= 1


async def test_title_search_ocr_noise_corrected_in_fields():
    text = _load("title_search_page1.txt")
    result = await extract_title_search(
        text=text, filename="title_search_page1.txt", case_id=None
    )
    payload = result.payload
    mortgage = next(
        lien for lien in payload["liens"] if lien["lien_type"] == "mortgage"
    )
    # OCR'd source has `$445,OOO.OO`; extractor must emit clean 445000.00
    assert "O" not in str(mortgage["amount"])
    assert Decimal(str(mortgage["amount"])) == Decimal("445000.00")


async def test_servicer_email_extracts_payoff_and_action_items():
    text = _load("servicer_email.txt")
    result = await extract_servicer_email(
        text=text, filename="servicer_email.txt", case_id=None
    )
    payload = result.payload

    # Payoff update should be present (the brief says $487,920 as of 3/1/2026)
    assert payload.get("payoff_update") is not None
    assert Decimal(str(payload["payoff_update"]["amount"])) == Decimal("487920.00")

    # Multiple action items
    assert len(payload["action_items"]) >= 3

    # Every action item has a source span
    for ai in payload["action_items"]:
        assert ai["source_spans"]


async def test_servicer_email_captures_attorney_and_transfer():
    text = _load("servicer_email.txt")
    result = await extract_servicer_email(
        text=text, filename="servicer_email.txt", case_id=None
    )
    payload = result.payload

    transfer = payload.get("transfer")
    assert transfer is not None
    assert "cooper" in (transfer.get("to_servicer") or "").lower()

    attorney = payload.get("attorney")
    assert attorney is not None
    assert attorney["name"]  # non-empty name captured


async def test_court_order_extracts_all_deadlines():
    text = _load("court_order.txt")
    result = await extract_court_order(
        text=text, filename="court_order.txt", case_id=None
    )
    payload = result.payload

    # The brief lists 3 clear dated obligations in the court order:
    #   April 12 (case management report)
    #   April 15 (proof of service)
    #   April 22 (case management conference)
    # The LLM may classify the conference as a `deadline` or as a
    # `required_appearance` — both are valid, so we union across all
    # dated items on the extraction.
    def _dates_from(rows, key):
        return {r.get(key) for r in rows if r.get(key)}

    dated = (
        _dates_from(payload.get("deadlines", []), "due_date")
        | _dates_from(payload.get("required_appearances", []), "deadline")
        | _dates_from(payload.get("filing_requirements", []), "deadline")
    )
    april_dates = {d for d in dated if d and d.startswith("2026-04")}
    assert len(april_dates) >= 3, (
        f"expected ≥3 April dated obligations across deadlines + "
        f"required_appearances + filing_requirements; got {april_dates}"
    )


async def test_court_order_has_case_number_and_court():
    text = _load("court_order.txt")
    result = await extract_court_order(
        text=text, filename="court_order.txt", case_id=None
    )
    payload = result.payload
    assert payload.get("case_number"), "case_number missing"
    assert payload.get("court"), "court missing"

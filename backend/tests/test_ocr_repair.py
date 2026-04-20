"""Tests for deterministic OCR-noise repair."""

from app.pipeline.ocr_repair import repair_ocr


def test_money_O_becomes_zero():
    out, stats = repair_ocr("Amount: $445,OOO.OO owed")
    assert out == "Amount: $445,000.00 owed"
    # 5 O's total: 3 in "OOO" + 2 in ".OO"
    assert stats["money_O_to_0"] == 5


def test_instrument_number_O_becomes_zero():
    out, stats = repair_ocr("Instrument No. 2O21-O123456 recorded")
    assert out == "Instrument No. 2021-0123456 recorded"
    assert stats["instrument_O_to_0"] == 2


def test_parcel_number_with_multiple_O():
    out, _ = repair_ocr("Tax Parcel No.: 33-5O22-O14-O29O")
    assert out == "Tax Parcel No.: 33-5022-014-0290"


def test_alpha_words_left_untouched():
    """We intentionally don't fix `T1TLE` or `Pa1metto`; the LLM handles those."""
    inp = "COMMONWEALTH LAND T1TLE INSURANCE COMPANY"
    out, stats = repair_ocr(inp)
    assert out == inp
    assert stats["total_replacements"] == 0


def test_dollar_sign_with_no_O_is_unchanged():
    inp = "Total: $1,234.56"
    out, _ = repair_ocr(inp)
    assert out == inp


def test_multiple_money_amounts_in_same_text():
    inp = "Mortgage $445,OOO.OO and HOA $3,42O.OO"
    out, stats = repair_ocr(inp)
    assert "$445,000.00" in out
    assert "$3,420.00" in out
    # 5 O's in "$445,OOO.OO" + 3 O's in "$3,42O.OO" = 8
    assert stats["money_O_to_0"] == 8


def test_stats_accumulate():
    inp = "$445,OOO.OO and 2O21-O123456"
    _, stats = repair_ocr(inp)
    assert stats["total_replacements"] == stats["money_O_to_0"] + stats["instrument_O_to_0"]
    assert stats["total_replacements"] >= 5


def test_empty_string():
    out, stats = repair_ocr("")
    assert out == ""
    assert stats["total_replacements"] == 0


def test_preserves_newlines_and_spacing():
    inp = "Line 1: $1OO.OO\nLine 2: text\n  Line 3: 2O21-O1"
    out, _ = repair_ocr(inp)
    assert out.count("\n") == inp.count("\n")
    assert "Line 1: $100.00" in out

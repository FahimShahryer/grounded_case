"""Chunker tests — no LLM, pure structure."""

from app.pipeline.chunk import chunk_document


def test_splits_on_blank_lines():
    text = "Paragraph one.\nStill one.\n\nParagraph two.\n\nParagraph three."
    chunks = chunk_document(text)
    assert len(chunks) == 3
    assert "Paragraph one." in chunks[0].text
    assert "Paragraph two." in chunks[1].text
    assert "Paragraph three." in chunks[2].text


def test_each_numbered_item_is_its_own_chunk():
    text = (
        "Schedule B — Exceptions\n"
        "\n"
        "1. Property taxes for 2025.\n"
        "   Amount: $8,247.00\n"
        "\n"
        "2. Mortgage from Rodriguez to Wells Fargo.\n"
        "   Amount: $445,000.00\n"
        "\n"
        "3. HOA lis pendens.\n"
        "   Amount: $3,420.00\n"
    )
    chunks = chunk_document(text)

    # Header + 3 numbered items
    assert len(chunks) == 4
    assert chunks[1].section_header.startswith("1.")
    assert chunks[2].section_header.startswith("2.")
    assert chunks[3].section_header.startswith("3.")
    assert "$445,000.00" in chunks[2].text
    # No numbered item spans two chunks
    for c in chunks[1:]:
        assert c.text.count("\n1. ") == 0 or c.text.startswith("1. ")


def test_numbered_items_start_new_chunks_even_without_blank_line():
    text = "1. First item line one.\n2. Second item.\n3. Third item."
    chunks = chunk_document(text)
    assert len(chunks) == 3
    assert chunks[0].text.startswith("1.")
    assert chunks[1].text.startswith("2.")
    assert chunks[2].text.startswith("3.")


def test_line_ranges_are_correct():
    text = "Line 1\nLine 2\n\nLine 4\nLine 5"
    chunks = chunk_document(text)
    assert len(chunks) == 2
    assert chunks[0].line_start == 1
    assert chunks[0].line_end == 2
    assert chunks[1].line_start == 4
    assert chunks[1].line_end == 5


def test_detects_all_caps_section_header():
    text = "SCHEDULE B - EXCEPTIONS\nBody line here.\n"
    chunks = chunk_document(text)
    assert chunks[0].section_header is not None
    assert "SCHEDULE B" in chunks[0].section_header


def test_rodriguez_title_search_page_1_structure():
    """Load the real fixture and assert sensible chunk boundaries."""
    from pathlib import Path

    path = Path("/app/data/rodriguez/sample_documents/title_search_page1.txt")
    raw = path.read_text(encoding="utf-8")
    chunks = chunk_document(raw, doc_type="title_search")

    # Expect ~8 chunks: header/intro + 6 numbered items + NOTE
    assert 6 <= len(chunks) <= 12, f"expected 6-12 chunks, got {len(chunks)}"

    # Each numbered Schedule B item should appear as its own chunk header.
    numbered_headers = [
        c.section_header for c in chunks if c.section_header and c.section_header[0].isdigit()
    ]
    assert len(numbered_headers) >= 6

    # Wells Fargo mortgage and HOA lis pendens should each be a complete,
    # single-chunk entry — not split across two chunks.
    mortgage_chunks = [c for c in chunks if "WELLS FARGO" in c.text]
    assert len(mortgage_chunks) == 1
    assert "445,OOO" in mortgage_chunks[0].text or "445,000" in mortgage_chunks[0].text
    assert "2O21-O123456" in mortgage_chunks[0].text or "2021-0123456" in mortgage_chunks[0].text

    hoa_chunks = [c for c in chunks if "PALMETT0" in c.text or "PALMETTO" in c.text]
    assert len(hoa_chunks) == 1

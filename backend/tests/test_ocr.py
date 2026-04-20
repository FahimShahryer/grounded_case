"""Tests for the tiered OCR module.

Strategy:
  - The text tier is trivial — cover routing + edge cases (empty, UTF-8).
  - The tesseract tier is exercised via a synthetic image-only PDF built
    with the same PIL pipeline used by `scripts/build_demo_scans`. This
    asserts the full rasterize-and-OCR roundtrip without depending on
    any committed PDF fixture.
  - The pdfplumber tier is covered by generating a real text-layer PDF
    with reportlab-style output from Pillow's PDF writer is NOT possible
    (PIL only writes images), so we verify the router's fall-through
    logic instead: force a PDF with no text layer and assert the engine
    lands on "tesseract".
"""

from __future__ import annotations

import io
import shutil
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from app.pipeline.ocr import extract_text

# ---------------------------------------------------------------- helpers


def _find_font():
    """Locate the DejaVu mono font installed in the container."""
    for p in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/dejavu/DejaVuSansMono.ttf",
    ]:
        if Path(p).exists():
            return ImageFont.truetype(p, 36)  # ~11pt @ 200dpi
    return ImageFont.load_default()


def _make_scanned_pdf(text: str) -> bytes:
    """Render ``text`` as an image-only PDF (no text layer). Returns bytes."""
    font = _find_font()
    # Sized generously so the text fits comfortably.
    w, h = 1700, 2200  # US Letter @ 200dpi
    img = Image.new("RGB", (w, h), color="white")
    draw = ImageDraw.Draw(img)
    y = 120
    for line in text.splitlines() or [""]:
        draw.text((120, y), line, fill="black", font=font)
        y += 56
    buf = io.BytesIO()
    img.save(buf, "PDF", resolution=200)
    return buf.getvalue()


def _make_png(text: str) -> bytes:
    """Return PNG bytes of ``text`` rendered at high contrast."""
    font = _find_font()
    img = Image.new("RGB", (1200, 260), color="white")
    draw = ImageDraw.Draw(img)
    y = 60
    for line in text.splitlines() or [""]:
        draw.text((60, y), line, fill="black", font=font)
        y += 56
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


# Skip OCR-dependent tests if tesseract isn't available (e.g. local run
# without the container's apt deps).
_TESSERACT_AVAILABLE = shutil.which("tesseract") is not None
needs_tesseract = pytest.mark.skipif(
    not _TESSERACT_AVAILABLE, reason="tesseract binary not installed"
)


# ---------------------------------------------------------------- text tier


def test_plain_text_utf8_routes_to_text_tier():
    result = extract_text(b"Hello, world.\nLine two.", "x.txt")
    assert result.engine == "text"
    assert result.text == "Hello, world.\nLine two."
    assert result.meta["chars"] == len(result.text)
    assert len(result.pages) == 1


def test_ocr_noisy_text_passes_through_unchanged():
    # The Rodriguez fixtures contain O-for-0 OCR noise; the ocr module
    # should NOT touch them — that's ocr_repair's job downstream.
    raw = b"Amount: $445,OOO.OO  Instrument: 2O21-O123456"
    result = extract_text(raw, "title.txt")
    assert result.engine == "text"
    assert "$445,OOO.OO" in result.text
    assert "2O21-O123456" in result.text


def test_empty_bytes_returns_empty():
    result = extract_text(b"", "x.txt")
    assert result.engine == "text"
    assert result.text == ""
    assert result.meta.get("empty") is True


def test_non_utf8_unknown_binary_falls_back_lossily():
    # Random bytes with no recognised magic — should be flagged in meta.
    raw = b"\x80\x81\x82 some garbage \xff"
    result = extract_text(raw, "junk.bin")
    assert result.engine == "text"
    assert "warning" in result.meta


# ---------------------------------------------------------------- tesseract via PDF


@needs_tesseract
def test_image_only_pdf_routes_to_tesseract():
    known = "HELLO WORLD\nTITLE SEARCH DOCUMENT\nAmount: 445000"
    pdf_bytes = _make_scanned_pdf(known)

    # PDF magic check
    assert pdf_bytes.startswith(b"%PDF-")

    result = extract_text(pdf_bytes, "scan.pdf")
    assert result.engine == "tesseract"
    assert result.pages and result.pages[0].mean_confidence is not None
    # OCR is tolerant — check that key tokens survived.
    ocr_text = result.text.upper()
    assert "HELLO" in ocr_text
    assert "TITLE" in ocr_text
    assert "445000" in ocr_text


@needs_tesseract
def test_tesseract_mean_confidence_is_meta_surfaced():
    pdf_bytes = _make_scanned_pdf("Line one.\nLine two.\nLine three.")
    result = extract_text(pdf_bytes, "c.pdf")
    assert result.engine == "tesseract"
    assert isinstance(result.meta.get("mean_confidence"), float)
    assert result.meta["rasterize_dpi"] == 200


# ---------------------------------------------------------------- tesseract via image


@needs_tesseract
def test_png_image_routes_to_tesseract():
    png = _make_png("RECORDED JULY 15 2021")
    assert png.startswith(b"\x89PNG")
    result = extract_text(png, "x.png")
    assert result.engine == "tesseract"
    assert "RECORDED" in result.text.upper()
    assert result.meta.get("image") is True


# ---------------------------------------------------------------- line preservation


@needs_tesseract
def test_tesseract_preserves_multi_line_structure():
    # Downstream extractors rely on line numbers via `number_lines()`.
    # The OCR output needs to have multiple newline-separated lines.
    pdf_bytes = _make_scanned_pdf("LINE ONE\nLINE TWO\nLINE THREE")
    result = extract_text(pdf_bytes, "ml.pdf")
    assert result.engine == "tesseract"
    # Should have at least 3 newline-separated logical lines.
    non_empty = [ln for ln in result.text.splitlines() if ln.strip()]
    assert len(non_empty) >= 3

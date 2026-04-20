"""Tiered text extraction from arbitrary uploaded bytes.

Tier routing
------------
1. UTF-8-decodable text   → engine="text"        (free, instant)
2. PDF with text layer    → engine="pdfplumber"  (free, milliseconds)
3. PDF without text layer → engine="tesseract"   (rasterize + OCR each page)
4. PNG / JPG image        → engine="tesseract"

The classifier and extractors downstream consume `OcrResult.text`, which is
line-preserving (`\\n` between lines, `\\n\\n` between pages). Every
SourceSpan in the rest of the pipeline cites by line number, so this
property is load-bearing.

`OcrResult.meta` is intended to be merged into `Document.meta["ocr"]` so
the engine + per-page confidence are queryable on the document detail page.

Vision-tier escalation (handwriting / very low confidence pages) is left
out of the take-home; `mean_confidence` is exposed so a reviewer can see
where it would plug in.
"""

from __future__ import annotations

import io
import logging
from typing import Literal

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

__all__ = ["OcrEngine", "OcrResult", "PageOcr", "extract_text"]


# Magic bytes — robust file-type detection without trusting extensions.
_PDF_MAGIC = b"%PDF-"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"

# If pdfplumber yields fewer than this many chars *per page on average*,
# treat the PDF as image-only and fall through to tesseract.
_PDFPLUMBER_MIN_CHARS_PER_PAGE = 30

# DPI for rasterization before OCR. 200 is the standard sweet spot —
# higher gives marginal accuracy gains at noticeable speed cost.
_OCR_DPI = 200

OcrEngine = Literal["text", "pdfplumber", "tesseract"]


class PageOcr(BaseModel):
    """One page of extracted text."""

    page_number: int  # 1-based
    text: str
    mean_confidence: float | None = Field(
        default=None,
        description="Mean per-word confidence (0-100). Tesseract only.",
    )


class OcrResult(BaseModel):
    """Full-document extraction result."""

    text: str
    engine: OcrEngine
    pages: list[PageOcr] = Field(default_factory=list)
    meta: dict = Field(default_factory=dict)


# ---------------------------------------------------------------- detection


def _looks_like_text(raw: bytes) -> bool:
    """True iff raw bytes decode cleanly as UTF-8 with no NUL bytes.

    PDFs and images always contain non-UTF-8 sequences, so this rejects
    them. ASCII text and UTF-8 text both pass.
    """
    try:
        decoded = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return False
    return "\x00" not in decoded


def _is_pdf(raw: bytes) -> bool:
    return raw[: len(_PDF_MAGIC)] == _PDF_MAGIC


def _is_image(raw: bytes) -> bool:
    return raw[: len(_PNG_MAGIC)] == _PNG_MAGIC or raw[: len(_JPEG_MAGIC)] == _JPEG_MAGIC


# ---------------------------------------------------------------- pdfplumber


def _extract_pdf_text_layer(raw: bytes) -> tuple[list[PageOcr], int]:
    """Read the embedded text layer of a PDF via pdfplumber.

    Returns ``(pages, total_chars)``. Total chars across all pages drives
    the fall-through decision.
    """
    import pdfplumber

    pages: list[PageOcr] = []
    total = 0
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            pages.append(PageOcr(page_number=i, text=text))
            total += len(text.strip())
    return pages, total


# ---------------------------------------------------------------- tesseract


def _ocr_image(image, page_number: int) -> PageOcr:
    """Run tesseract on a PIL image; reconstruct line-preserving text."""
    import pytesseract

    data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)

    # Group words by (block, par, line) to rebuild line structure.
    lines: dict[tuple[int, int, int, int], list[str]] = {}
    line_order: list[tuple[int, int, int, int]] = []
    confs: list[float] = []
    n = len(data["text"])
    for i in range(n):
        word = (data["text"][i] or "").strip()
        if not word:
            continue
        key = (
            int(data["page_num"][i]),
            int(data["block_num"][i]),
            int(data["par_num"][i]),
            int(data["line_num"][i]),
        )
        if key not in lines:
            line_order.append(key)
            lines[key] = []
        lines[key].append(word)
        try:
            c = float(data["conf"][i])
        except (ValueError, TypeError):
            c = -1.0
        if c >= 0:
            confs.append(c)

    text = "\n".join(" ".join(lines[k]) for k in line_order)
    mean_conf = sum(confs) / len(confs) if confs else None
    return PageOcr(page_number=page_number, text=text, mean_confidence=mean_conf)


def _ocr_pdf_pages(raw: bytes) -> list[PageOcr]:
    """Rasterize every PDF page at OCR DPI and OCR each one."""
    from pdf2image import convert_from_bytes

    images = convert_from_bytes(raw, dpi=_OCR_DPI)
    return [_ocr_image(img, i) for i, img in enumerate(images, start=1)]


def _ocr_image_bytes(raw: bytes) -> PageOcr:
    """OCR raw PNG/JPG bytes."""
    from PIL import Image

    img = Image.open(io.BytesIO(raw))
    return _ocr_image(img, page_number=1)


# ---------------------------------------------------------------- public API


def extract_text(raw_bytes: bytes, filename: str | None = None) -> OcrResult:
    """Tiered text extraction.

    Parameters
    ----------
    raw_bytes
        The raw file content (text, PDF, or image).
    filename
        Optional, only used for logging.

    Returns
    -------
    OcrResult
        ``.text`` is the extracted document text with newlines preserved.
        ``.meta`` is safe to merge into ``Document.meta["ocr"]``.
    """
    if not raw_bytes:
        return OcrResult(text="", engine="text", pages=[], meta={"empty": True})

    # Tier 1 — bytes are already valid UTF-8 text.
    if _looks_like_text(raw_bytes):
        text = raw_bytes.decode("utf-8")
        return OcrResult(
            text=text,
            engine="text",
            pages=[PageOcr(page_number=1, text=text)],
            meta={"chars": len(text)},
        )

    # Tier 2/3 — PDF
    if _is_pdf(raw_bytes):
        try:
            pages, total = _extract_pdf_text_layer(raw_bytes)
        except Exception as e:
            log.warning("pdfplumber failed on %s: %s — falling through to OCR", filename, e)
            pages, total = [], 0

        # Use the text layer when it's substantive.
        if pages and total >= _PDFPLUMBER_MIN_CHARS_PER_PAGE * len(pages):
            text = "\n\n".join(p.text for p in pages)
            return OcrResult(
                text=text,
                engine="pdfplumber",
                pages=pages,
                meta={
                    "pages": len(pages),
                    "chars": total,
                    "chars_per_page": total // max(len(pages), 1),
                },
            )

        # Sparse / missing text layer → rasterize + tesseract.
        log.info(
            "pdfplumber: %d chars across %d pages on %s — escalating to tesseract",
            total,
            len(pages),
            filename,
        )
        ocr_pages = _ocr_pdf_pages(raw_bytes)
        text = "\n\n".join(p.text for p in ocr_pages)
        confs = [p.mean_confidence for p in ocr_pages if p.mean_confidence is not None]
        mean_conf = sum(confs) / len(confs) if confs else None
        return OcrResult(
            text=text,
            engine="tesseract",
            pages=ocr_pages,
            meta={
                "pages": len(ocr_pages),
                "mean_confidence": round(mean_conf, 2) if mean_conf is not None else None,
                "pdfplumber_chars": total,
                "rasterize_dpi": _OCR_DPI,
            },
        )

    # Tier 3 — single image
    if _is_image(raw_bytes):
        page = _ocr_image_bytes(raw_bytes)
        return OcrResult(
            text=page.text,
            engine="tesseract",
            pages=[page],
            meta={
                "image": True,
                "mean_confidence": (
                    round(page.mean_confidence, 2)
                    if page.mean_confidence is not None
                    else None
                ),
            },
        )

    # Unknown binary — last-ditch decode-with-replace, flagged.
    log.warning(
        "extract_text: unknown bytes for %s (first 8=%r) — falling back to lossy decode",
        filename,
        raw_bytes[:8],
    )
    fallback = raw_bytes.decode("utf-8", errors="replace")
    return OcrResult(
        text=fallback,
        engine="text",
        pages=[PageOcr(page_number=1, text=fallback)],
        meta={"warning": "unknown bytes; lossy UTF-8 fallback"},
    )

"""Render the Rodriguez text fixtures as image-only PDFs for the OCR demo.

The output mirrors `ai_engineer_assignment_data/` layout but every
``.txt`` becomes a multi-page ``.pdf`` whose content is PURELY raster —
no text layer. Running it through the pipeline forces the Tesseract
tier to fire, proving real OCR end-to-end.

Usage
-----
    docker compose exec backend python -m scripts.build_demo_scans

After the script runs, commit the output under ``data_demo_scans/``.
The PDFs are deterministic (fixed RNG seed) so re-running produces
byte-identical files.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SOURCE_DIR = Path("/app/data/rodriguez/sample_documents")
SOURCE_CTX = Path("/app/data/rodriguez/case_context.json")

OUT_ROOT = Path("/app/data/rodriguez_scans")
OUT_DOCS = OUT_ROOT / "sample_documents"
OUT_CTX = OUT_ROOT / "case_context.json"

# Page geometry — standard US Letter at 200 DPI.
DPI = 200
PAGE_WIDTH_IN = 8.5
PAGE_HEIGHT_IN = 11.0
MARGIN_IN = 0.75
FONT_PT = 11
LINE_SPACING = 1.35
JITTER_PX = 1  # tiny per-line jitter so pages feel scanned, not typeset


def _load_font():
    # DejaVu Sans Mono ships with fonts-dejavu-core (installed in the Dockerfile).
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/dejavu/DejaVuSansMono.ttf",
    ]
    size_px = int(FONT_PT * DPI / 72)
    for p in candidates:
        if Path(p).exists():
            return ImageFont.truetype(p, size_px)
    return ImageFont.load_default()


def _render_lines_to_pages(lines: list[str], font) -> list[Image.Image]:
    page_w = int(PAGE_WIDTH_IN * DPI)
    page_h = int(PAGE_HEIGHT_IN * DPI)
    margin = int(MARGIN_IN * DPI)
    line_height = int(FONT_PT * DPI / 72 * LINE_SPACING)
    max_y = page_h - margin

    rng = random.Random(0)
    pages: list[Image.Image] = []
    i = 0
    n = len(lines) or 1
    while i < n:
        img = Image.new("RGB", (page_w, page_h), color="white")
        draw = ImageDraw.Draw(img)
        y = margin
        while i < len(lines) and y + line_height <= max_y:
            line = lines[i]
            x = margin + rng.randint(-JITTER_PX, JITTER_PX)
            yj = y + rng.randint(-JITTER_PX, JITTER_PX)
            draw.text((x, yj), line, fill="black", font=font)
            y += line_height
            i += 1
        pages.append(img)
        if not lines:
            break
    return pages


def _save_multipage_pdf(pages: list[Image.Image], out_path: Path) -> None:
    if not pages:
        return
    out_path.parent.mkdir(parents=True, exist_ok=True)
    head, *rest = pages
    head.save(
        str(out_path),
        "PDF",
        resolution=DPI,
        save_all=True,
        append_images=rest,
    )


def _write_case_context() -> None:
    if not SOURCE_CTX.exists():
        print(f"[build] WARN: {SOURCE_CTX} missing; skipping case_context.json copy")
        return
    ctx = json.loads(SOURCE_CTX.read_text(encoding="utf-8"))
    # Distinct case_number so the scanned demo coexists with the regular
    # Rodriguez case in the same DB.
    ctx["case_number"] = f"{ctx['case_number']}-SCAN"
    note = ctx.get("notes") or ""
    marker = "[Synthetic scanned PDFs for OCR tier demo.]"
    if marker not in note:
        ctx["notes"] = (note + " " + marker).strip()
    OUT_CTX.parent.mkdir(parents=True, exist_ok=True)
    OUT_CTX.write_text(json.dumps(ctx, indent=2) + "\n", encoding="utf-8")
    print(f"[build] wrote {OUT_CTX}")


def main() -> None:
    if not SOURCE_DIR.exists():
        raise SystemExit(f"[build] ERROR: {SOURCE_DIR} not found")

    OUT_DOCS.mkdir(parents=True, exist_ok=True)
    _write_case_context()
    font = _load_font()

    txt_paths = sorted(SOURCE_DIR.glob("*.txt"))
    if not txt_paths:
        raise SystemExit(f"[build] ERROR: no .txt fixtures in {SOURCE_DIR}")

    for src in txt_paths:
        text = src.read_text(encoding="utf-8")
        lines = text.splitlines()
        pages = _render_lines_to_pages(lines, font)
        out = OUT_DOCS / f"{src.stem}.pdf"
        _save_multipage_pdf(pages, out)
        print(f"[build] {src.name} ({len(lines)} lines) → {out} ({len(pages)} page(s))")

    print("[build] Done. Next:")
    print("        make seed-scanned        # ingest these scans")
    print("        make process-scanned     # full pipeline + drafts")


if __name__ == "__main__":
    main()

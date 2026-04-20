"""Seed the Rodriguez case and its 4 sample documents.

Runs inside the backend container against the real database. Idempotent:
rerunning skips the case (by case_number) and skips documents (by sha).

Usage:
    docker compose exec backend python -m scripts.seed
    # or:  make seed
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from app.db.session import SessionLocal
from app.db.tables import Case, Document
from app.pipeline.classify import classify_document
from app.pipeline.ocr import extract_text
from app.storage import minio_client

# Default to the Rodriguez fixtures; override with CASE_DATA_DIR to
# point at a different case's files (used by seed-case-2 / seed-scanned).
DATA_DIR = Path(os.environ.get("CASE_DATA_DIR", "/app/data/rodriguez"))


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    # case_context.json uses "February 8, 2021" style
    from datetime import datetime

    for fmt in ("%B %d, %Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


async def _ensure_case() -> Case:
    ctx_path = DATA_DIR / "case_context.json"
    if not ctx_path.exists():
        print(f"[seed] ERROR: {ctx_path} not found", file=sys.stderr)
        sys.exit(1)

    ctx = json.loads(ctx_path.read_text(encoding="utf-8"))

    async with SessionLocal() as session:
        existing = await session.execute(
            select(Case).where(Case.case_number == ctx["case_number"])
        )
        case = existing.scalar_one_or_none()
        if case is not None:
            print(f"[seed] Case {case.case_number} already exists (id={case.id}) — skipping")
            return case

        case = Case(
            case_number=ctx["case_number"],
            borrower=ctx["borrower"],
            property_address=ctx["property_address"],
            county=ctx.get("county"),
            state=ctx.get("state"),
            servicer=ctx.get("servicer"),
            loan_number=ctx.get("loan_number"),
            loan_amount=Decimal(str(ctx["loan_amount"])) if ctx.get("loan_amount") else None,
            loan_date=_parse_date(ctx.get("loan_date")),
            default_date=_parse_date(ctx.get("default_date")),
            current_status=ctx.get("current_status"),
            notes=ctx.get("notes"),
            context=ctx,
        )
        session.add(case)
        await session.commit()
        await session.refresh(case)
        print(f"[seed] Created case {case.case_number} (id={case.id})")
        return case


async def _ingest_sample_docs(case: Case) -> None:
    docs_dir = DATA_DIR / "sample_documents"
    if not docs_dir.exists():
        print(f"[seed] ERROR: {docs_dir} not found", file=sys.stderr)
        sys.exit(1)

    # Pick up text, scanned PDFs, and images uniformly — the OCR layer
    # routes each through the right tier.
    patterns = ("*.txt", "*.pdf", "*.png", "*.jpg", "*.jpeg")
    paths = sorted({p for pat in patterns for p in docs_dir.glob(pat)})
    if not paths:
        print(
            f"[seed] No documents (.txt/.pdf/.png/.jpg) found in {docs_dir}",
            file=sys.stderr,
        )
        sys.exit(1)

    for path in paths:
        raw_bytes = path.read_bytes()
        sha = hashlib.sha256(raw_bytes).hexdigest()

        async with SessionLocal() as session:
            existing = await session.execute(
                select(Document).where(
                    Document.case_id == case.id, Document.content_sha256 == sha
                )
            )
            dup = existing.scalar_one_or_none()
            if dup is not None:
                print(f"[seed] {path.name}: already loaded (id={dup.id}, type={dup.doc_type})")
                continue

            ocr = extract_text(raw_bytes, path.name)
            raw_text = ocr.text

            classification = await classify_document(
                text=raw_text, filename=path.name, case_id=case.id
            )

            doc = Document(
                case_id=case.id,
                filename=path.name,
                doc_type=classification.doc_type.value,
                raw_text=raw_text,
                content_sha256=sha,
                meta={"ocr": {"engine": ocr.engine, **ocr.meta}},
            )
            session.add(doc)
            await session.commit()
            await session.refresh(doc)

            try:
                storage_key = minio_client.put_document(
                    case_id=case.id,
                    document_id=doc.id,
                    filename=path.name,
                    raw_bytes=raw_bytes,
                )
                doc.storage_key = storage_key
                await session.commit()
            except Exception as e:
                print(f"[seed] {path.name}: MinIO upload failed ({e}); continuing")

            print(
                f"[seed] {path.name}: ocr={ocr.engine} "
                f"({len(raw_text)} chars) → classified as {doc.doc_type} "
                f"({classification.rationale}) → id={doc.id}"
                + (f" → minio:{doc.storage_key}" if doc.storage_key else "")
            )


async def main() -> None:
    case = await _ensure_case()
    await _ingest_sample_docs(case)
    print("[seed] Done.")


if __name__ == "__main__":
    asyncio.run(main())

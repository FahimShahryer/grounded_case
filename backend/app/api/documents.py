import hashlib
import logging
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.api.deps import SessionDep
from app.db.tables import Case, Document
from app.models.document import DocumentDetail, DocumentOut
from app.models.enums import DocType
from app.pipeline.classify import classify_document
from app.pipeline.ocr import extract_text
from app.storage import minio_client

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["documents"])


def _serialize_document(doc: Document) -> DocumentOut:
    return DocumentOut(
        id=doc.id,
        case_id=doc.case_id,
        filename=doc.filename,
        doc_type=DocType(doc.doc_type),
        content_sha256=doc.content_sha256,
        has_cleaned_text=doc.cleaned_text is not None,
        meta=doc.meta or {},
        storage_key=doc.storage_key,
        created_at=doc.created_at,
    )


@router.post(
    "/cases/{case_id}/documents",
    response_model=DocumentOut,
    status_code=201,
)
async def upload_document(
    case_id: int,
    session: SessionDep,
    file: Annotated[UploadFile, File()],
    doc_type: Annotated[DocType | None, "Override classifier"] = None,
) -> DocumentOut:
    case = await session.get(Case, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    raw_bytes = await file.read()
    sha = hashlib.sha256(raw_bytes).hexdigest()

    # Idempotency: same file uploaded twice → return the existing row.
    # Hash before OCR so we don't pay the OCR cost on duplicate uploads.
    existing = await session.execute(
        select(Document).where(
            Document.case_id == case_id, Document.content_sha256 == sha
        )
    )
    already = existing.scalar_one_or_none()
    if already is not None:
        return _serialize_document(already)

    # Tiered text extraction: text → pdfplumber → tesseract.
    ocr = extract_text(raw_bytes, file.filename)
    raw_text = ocr.text

    if doc_type is None:
        classification = await classify_document(
            text=raw_text,
            filename=file.filename,
            case_id=case_id,
        )
        doc_type = classification.doc_type

    doc = Document(
        case_id=case_id,
        filename=file.filename or "unnamed",
        doc_type=doc_type.value,
        raw_text=raw_text,
        content_sha256=sha,
        meta={"ocr": {"engine": ocr.engine, **ocr.meta}},
    )
    session.add(doc)
    await session.commit()
    await session.refresh(doc)

    # Persist the original bytes to MinIO keyed by the freshly-assigned
    # doc.id. Canonical path: cases/{case_id}/docs/{doc.id}/{filename}.
    # If MinIO is down we log and proceed — the pipeline still works off
    # raw_text; the blob is for re-OCR + user downloads.
    try:
        storage_key = minio_client.put_document(
            case_id=case_id,
            document_id=doc.id,
            filename=file.filename,
            raw_bytes=raw_bytes,
            content_type=file.content_type,
        )
        doc.storage_key = storage_key
        await session.commit()
        await session.refresh(doc)
    except Exception:
        log.exception("MinIO upload failed for doc %d; continuing without blob", doc.id)

    return _serialize_document(doc)


@router.get(
    "/cases/{case_id}/documents",
    response_model=list[DocumentOut],
)
async def list_documents(case_id: int, session: SessionDep) -> list[DocumentOut]:
    case = await session.get(Case, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    result = await session.execute(
        select(Document).where(Document.case_id == case_id).order_by(Document.id)
    )
    return [_serialize_document(d) for d in result.scalars()]


@router.get("/documents/{document_id}", response_model=DocumentDetail)
async def get_document(document_id: int, session: SessionDep) -> DocumentDetail:
    doc = await session.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return DocumentDetail(
        id=doc.id,
        case_id=doc.case_id,
        filename=doc.filename,
        doc_type=DocType(doc.doc_type),
        content_sha256=doc.content_sha256,
        has_cleaned_text=doc.cleaned_text is not None,
        raw_text=doc.raw_text,
        cleaned_text=doc.cleaned_text,
        meta=doc.meta,
        created_at=doc.created_at,
    )


@router.get("/documents/{document_id}/download")
async def download_document(document_id: int, session: SessionDep) -> RedirectResponse:
    """Redirect to a short-lived presigned URL for the original file.

    The backend never streams the bytes itself — the browser fetches them
    directly from MinIO. The URL expires in 5 minutes so it's not usable
    as a durable share link.
    """
    doc = await session.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if not doc.storage_key:
        raise HTTPException(
            status_code=410,
            detail="Original bytes not retained for this document (legacy upload).",
        )
    url = minio_client.presigned_download_url(doc.storage_key)
    return RedirectResponse(url=url, status_code=307)

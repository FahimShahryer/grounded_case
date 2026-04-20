from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import DocType


class DocumentCreate(BaseModel):
    filename: str
    doc_type: DocType | None = None  # None → let classifier decide
    raw_text: str


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    case_id: int
    filename: str
    doc_type: DocType
    content_sha256: str
    has_cleaned_text: bool = Field(
        default=False, description="True once OCR-repair has been applied."
    )
    meta: dict = Field(
        default_factory=dict,
        description="Free-form metadata. `meta.ocr.engine` indicates which "
        "extractor produced raw_text (text / pdfplumber / tesseract).",
    )
    storage_key: str | None = Field(
        default=None,
        description="MinIO object key for the original bytes. When present, "
        "GET /api/documents/{id}/download redirects to a presigned URL.",
    )
    created_at: datetime


class DocumentDetail(DocumentOut):
    """Full document including text, for single-item GETs."""

    raw_text: str
    cleaned_text: str | None

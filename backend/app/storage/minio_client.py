"""MinIO blob storage wrapper for uploaded documents.

Why a wrapper:
  - Two clients in the same process — the backend reaches MinIO over
    the docker compose network (`minio:9000`), but presigned URLs are
    handed to the user's browser and must embed a hostname the browser
    can resolve (`localhost:9000` in dev). The wrapper picks the right
    client for each op.
  - Bucket is ensured lazily on first use so local dev / CI doesn't
    need a separate bootstrap step.
  - Object keys follow `cases/{case_id}/docs/{document_id}/{filename}`
    so MinIO console browsing is human-friendly.
"""

from __future__ import annotations

import io
import logging
import re
from datetime import timedelta

from minio import Minio
from minio.error import S3Error

from app.config import settings

log = logging.getLogger(__name__)

__all__ = [
    "delete_document",
    "ensure_bucket",
    "object_key_for",
    "presigned_download_url",
    "put_document",
]

_DOWNLOAD_URL_TTL = timedelta(minutes=5)
_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


# ---------------------------------------------------------------- clients


def _build_client(endpoint: str) -> Minio:
    # Setting `region` explicitly stops the client from doing a live
    # `GET /bucket?location=` probe at first use — important for the
    # public client which points at a hostname only the browser can resolve.
    return Minio(
        endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
        region="us-east-1",
    )


_internal_client: Minio | None = None
_public_client: Minio | None = None


def _internal() -> Minio:
    """Client pointed at the container-network endpoint. Use for put/get."""
    global _internal_client
    if _internal_client is None:
        _internal_client = _build_client(settings.minio_internal_endpoint)
    return _internal_client


def _public() -> Minio:
    """Client pointed at the user-facing endpoint. Use for presigned URLs only."""
    global _public_client
    if _public_client is None:
        _public_client = _build_client(settings.minio_public_endpoint)
    return _public_client


# ---------------------------------------------------------------- bucket


_bucket_ensured = False


def ensure_bucket() -> None:
    """Create the bucket on first use. Idempotent."""
    global _bucket_ensured
    if _bucket_ensured:
        return
    client = _internal()
    try:
        if not client.bucket_exists(settings.minio_bucket):
            client.make_bucket(settings.minio_bucket)
            log.info("created MinIO bucket %r", settings.minio_bucket)
    except S3Error as e:
        log.exception("failed to ensure MinIO bucket %r", settings.minio_bucket)
        raise RuntimeError(f"MinIO bucket setup failed: {e}") from e
    _bucket_ensured = True


# ---------------------------------------------------------------- keys


def _safe_filename(filename: str | None) -> str:
    """Strip anything that could break a URL or escape the prefix."""
    if not filename:
        return "unnamed"
    # Keep just the basename, collapse weird chars.
    base = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    base = _SAFE_FILENAME_RE.sub("_", base).strip("._")
    return base or "unnamed"


def object_key_for(case_id: int, document_id: int, filename: str | None) -> str:
    """Canonical object key — human-browsable in the MinIO console."""
    return f"cases/{case_id}/docs/{document_id}/{_safe_filename(filename)}"


# ---------------------------------------------------------------- operations


def put_document(
    *,
    case_id: int,
    document_id: int,
    filename: str | None,
    raw_bytes: bytes,
    content_type: str | None = None,
) -> str:
    """Upload bytes to MinIO. Returns the storage_key to persist on the doc row."""
    ensure_bucket()
    key = object_key_for(case_id, document_id, filename)
    _internal().put_object(
        bucket_name=settings.minio_bucket,
        object_name=key,
        data=io.BytesIO(raw_bytes),
        length=len(raw_bytes),
        content_type=content_type or "application/octet-stream",
    )
    return key


def presigned_download_url(
    storage_key: str, *, expires: timedelta = _DOWNLOAD_URL_TTL
) -> str:
    """Return a time-limited URL the user's browser can GET to download the file.

    Important: the public client never actually connects — `presigned_get_object`
    only signs a URL using its configured hostname. That hostname (`localhost:9000`
    in dev) is what the browser will hit, which is distinct from the internal
    endpoint (`minio:9000`) that the backend uses for real ops.
    """
    return _public().presigned_get_object(
        bucket_name=settings.minio_bucket,
        object_name=storage_key,
        expires=expires,
    )


def delete_document(storage_key: str) -> None:
    """Remove a blob — called when a document row is deleted."""
    try:
        _internal().remove_object(settings.minio_bucket, storage_key)
    except S3Error as e:
        # Log and swallow — orphan blobs are cheaper than failed deletes.
        log.warning("failed to delete blob %r: %s", storage_key, e)

"""Tests for the MinIO blob storage wrapper.

These tests hit a real MinIO running in docker compose — we don't mock.
Skipped cleanly if the MinIO endpoint isn't reachable (e.g. running
tests locally without the full stack).
"""

from __future__ import annotations

import socket

import pytest

from app.config import settings
from app.storage import minio_client


def _minio_reachable() -> bool:
    host, _, port = settings.minio_internal_endpoint.partition(":")
    try:
        with socket.create_connection((host, int(port or 9000)), timeout=1):
            return True
    except OSError:
        return False


needs_minio = pytest.mark.skipif(not _minio_reachable(), reason="MinIO not reachable")


def test_object_key_uses_case_and_doc_ids():
    key = minio_client.object_key_for(
        case_id=7, document_id=42, filename="court_order.pdf"
    )
    assert key == "cases/7/docs/42/court_order.pdf"


def test_object_key_sanitizes_filename():
    # strips path components + replaces weird chars
    key = minio_client.object_key_for(
        case_id=1, document_id=1, filename="../evil path/a b c*.pdf"
    )
    assert key.startswith("cases/1/docs/1/")
    assert ".." not in key
    assert "/" not in key.removeprefix("cases/1/docs/1/")
    assert "*" not in key
    assert " " not in key


def test_object_key_handles_missing_filename():
    key = minio_client.object_key_for(case_id=1, document_id=1, filename=None)
    assert key == "cases/1/docs/1/unnamed"


@needs_minio
def test_put_stores_bytes_verbatim():
    """Upload bytes via put_document and read them back via the internal client."""
    raw = b"%PDF-1.4\nfake pdf body\n%%EOF\n"
    storage_key = minio_client.put_document(
        case_id=999,
        document_id=999,
        filename="roundtrip.pdf",
        raw_bytes=raw,
        content_type="application/pdf",
    )
    assert storage_key == "cases/999/docs/999/roundtrip.pdf"

    # Fetch via the internal client (presigned URLs use the public
    # hostname which isn't reachable from inside the test container).
    client = minio_client._internal()
    resp = client.get_object(settings.minio_bucket, storage_key)
    try:
        body = resp.read()
    finally:
        resp.close()
        resp.release_conn()
    assert body == raw


@needs_minio
def test_presigned_url_is_well_formed():
    """presigned_download_url produces a URL with the PUBLIC hostname."""
    raw = b"content"
    key = minio_client.put_document(
        case_id=998, document_id=998, filename="x.bin", raw_bytes=raw
    )
    url = minio_client.presigned_download_url(key)
    # It should point at the public endpoint (what the browser will use),
    # not the internal one.
    assert settings.minio_public_endpoint in url
    assert settings.minio_internal_endpoint not in url
    # AWS Sig V4 query params are present.
    assert "X-Amz-Signature=" in url
    assert "X-Amz-Expires=300" in url


@needs_minio
def test_delete_is_idempotent():
    """Deleting a missing key should not raise."""
    minio_client.delete_document("cases/999/docs/9999/does-not-exist.pdf")

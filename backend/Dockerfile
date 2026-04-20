# syntax=docker/dockerfile:1.7
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

# System deps for the tiered OCR pipeline:
#   tesseract-ocr  → real OCR engine for scans / images
#   poppler-utils  → pdf2image needs pdftoppm to rasterize PDFs
#   fonts-dejavu   → so build_demo_scans can render synthetic scanned PDFs
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        poppler-utils \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies first so Docker can cache them when app code changes.
COPY pyproject.toml ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-install-project

# Copy application source.
COPY . .

# Activate the virtualenv created by uv.
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

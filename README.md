# Grounded Case AI

Ingests messy legal documents → extracts typed facts with citations → retrieves grounded evidence → generates draft memos → learns from operator edits.

Sample data is synthetic (Rodriguez + Thompson foreclosure cases).
For design and engineering details, see [ARCHITECTURE_short.md](ARCHITECTURE_short.md) or [ARCHITECTURE_full.md](ARCHITECTURE_full.md). Also you can check the full workflow diagram in the [explained](explained/) folder.


---

## Prerequisites

- Docker + Docker Compose
- An OpenAI API key

## Setup

```bash
cp .env.example .env          # then add your OPENAI_API_KEY
make up                        # start postgres / minio / backend / frontend
make migrate                   # apply schema
make seed                      # load the Rodriguez fixture case
```

## Open in a browser

| URL | Purpose |
|---|---|
| http://localhost:3000 | Case list + "New case" button |
| http://localhost:3000/cases/1 | Case detail — upload docs, run pipeline, generate drafts |
| http://localhost:3000/learning | Mined patterns + templates, "Run miner" button |
| http://localhost:8000/docs | OpenAPI / Swagger UI for every endpoint |
| http://localhost:9001 | MinIO console — login `minioadmin` / `minioadmin` |

---

## Demo path

```bash
# core pipeline on the demo case
curl -X POST http://localhost:8000/api/cases/1/process
curl -X POST http://localhost:8000/api/cases/1/drafts \
  -H "Content-Type: application/json" \
  -d '{"draft_type":"title_review_summary"}'

# learning loop
make seed-edits              # ingest sample_edits.json
make mine                    # mine durable patterns from edits
make eval                    # → outputs/evaluation.md (v1 vs v2)

# OCR demo — image-only PDFs through Tesseract
make build-demo-scans
make seed-scanned
make process-scanned

# generalization proof — synthetic Thompson case with IRS tax lien
make seed-case-2
make process-case-2
```

---

## Commands reference

```bash
# services
make up / down / fresh / logs
make shell-backend / shell-db

# data
make seed / seed-edits / seed-reset
make seed-case-2 / seed-scanned
make build-demo-scans

# pipeline
make mine / eval
make process-case-2 / process-scanned

# dev
make test / lint
make migrate / migrate-create msg="..."
```


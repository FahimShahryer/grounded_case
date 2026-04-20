.PHONY: up down logs logs-backend logs-frontend shell-backend shell-db fresh \
	test lint format migrate migrate-down migrate-create migrate-status

up:
	docker compose up --build

up-detached:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f

logs-backend:
	docker compose logs -f backend

logs-frontend:
	docker compose logs -f frontend

shell-backend:
	docker compose exec backend bash

shell-db:
	docker compose exec postgres psql -U postgres -d caseai

fresh:
	docker compose down -v
	docker compose up --build

test:
	docker compose exec backend pytest

lint:
	docker compose exec backend ruff check .

format:
	docker compose exec backend ruff format .

# --- Seed sample data ---
seed:
	docker compose exec backend python -m scripts.seed

seed-edits:
	docker compose exec backend python -m scripts.seed_edits

seed-reset:
	docker compose exec postgres psql -U postgres -d caseai -c "TRUNCATE cases, documents, extractions, facts, fact_evidence, chunks, drafts, edits, llm_calls RESTART IDENTITY CASCADE;"
	docker compose exec backend python -m scripts.seed

mine:
	curl -s -X POST http://localhost:8000/api/learning/mine | python -m json.tool

# --- Step 10: evaluation + Case 2 generalization ---
eval:
	docker compose exec backend python -m scripts.eval

seed-case-2:
	docker compose exec -e CASE_DATA_DIR=/app/data/thompson backend python -m scripts.seed

# --- OCR demo: render Rodriguez fixtures as image-only PDFs ---
build-demo-scans:
	docker compose exec backend python -m scripts.build_demo_scans

seed-scanned:
	docker compose exec -e CASE_DATA_DIR=/app/data/rodriguez_scans backend python -m scripts.seed

process-scanned:
	@CASE_ID=$$(curl -s http://localhost:8000/api/cases | python -c "import json,sys;print(next(c['id'] for c in json.load(sys.stdin) if c['case_number'].endswith('-SCAN')))") && \
	echo "Processing scanned case id=$$CASE_ID" && \
	curl -s -X POST http://localhost:8000/api/cases/$$CASE_ID/process | python -m json.tool && \
	for d in title_review_summary case_status_memo; do \
	  echo "--- generating $$d ---" && \
	  curl -s -X POST http://localhost:8000/api/cases/$$CASE_ID/drafts -H "Content-Type: application/json" -d "{\"draft_type\":\"$$d\"}" | python -c "import json,sys;d=json.load(sys.stdin);print('draft id=',d['id'],' template v',d['template_version'])"; \
	done

process-case-2:
	@CASE_ID=$$(curl -s http://localhost:8000/api/cases | python -c "import json,sys;print(next(c['id'] for c in json.load(sys.stdin) if c['case_number']=='2026-FC-03217'))") && \
	echo "Processing case id=$$CASE_ID" && \
	curl -s -X POST http://localhost:8000/api/cases/$$CASE_ID/process | python -m json.tool && \
	for d in title_review_summary case_status_memo; do \
	  echo "--- generating $$d ---" && \
	  curl -s -X POST http://localhost:8000/api/cases/$$CASE_ID/drafts -H "Content-Type: application/json" -d "{\"draft_type\":\"$$d\"}" | python -c "import json,sys;d=json.load(sys.stdin);print('draft id=',d['id'],' template v',d['template_version'])"; \
	done

# --- Alembic ---
migrate:
	docker compose exec backend alembic upgrade head

migrate-down:
	docker compose exec backend alembic downgrade -1

migrate-status:
	docker compose exec backend alembic current

migrate-create:
	@[ -n "$(msg)" ] || (echo 'usage: make migrate-create msg="description"'; exit 1)
	docker compose exec backend alembic revision --autogenerate -m "$(msg)"

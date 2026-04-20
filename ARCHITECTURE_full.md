# Architecture

A document-understanding + grounded-drafting pipeline for a legal workflow.
Messy documents in → cited drafts out → system improves when operators edit.

This doc walks the system layer by layer, with a running example from
an example case.

---

## One picture

```
┌──────────────────────────────────────────────────────────────────────┐
│ 1. STORAGE                                                           │
│    Postgres (11 tables) + pgvector   |   MinIO (original file)       │
├──────────────────────────────────────────────────────────────────────┤
│ 2. INGESTION                                                         │
│    bytes → SHA dedup → tiered OCR → classify → DB row + MinIO blob   │
│    (magic-byte routing: text / pdfplumber / tesseract(OCR))          │
├──────────────────────────────────────────────────────────────────────┤
│ 3. KNOWLEDGE GRAPH                                                   │
│    OCR-repair → per-doc-type LLM extractors → LLM resolver           │
│    → facts table + fact_evidence (M:N citations)                     │
│    (temporal: latest wins, previous_values preserved)                │
├──────────────────────────────────────────────────────────────────────┤
│ 4. RETRIEVAL INDEX   (parallel to the knowledge graph)               │
│    cleaned_text → chunks → embeddings (pgvector HNSW) + BM25         │
├──────────────────────────────────────────────────────────────────────┤
│ 5. EVIDENCE PACKS                                                    │
│    per-section: structured_facts + text_evidence + gaps + conflicts  │
│    (hybrid BM25+vector → RRF → LLM reranker → top 5)                 │
├──────────────────────────────────────────────────────────────────────┤
│ 6. GROUNDED GENERATION                                               │
│    Generator (structured output) → Verifier (deterministic + LLM)    │
│    → retry up to 2x on failure → DraftContent → markdown             │
├──────────────────────────────────────────────────────────────────────┤
│ 7. LEARNING LOOP                                                     │
│    Edit → diff → classify → mine → Pattern → Template bump           │
│    → next generation reads active patterns → verifier enforces       │
├──────────────────────────────────────────────────────────────────────┤
│ cross-cutting:  llm/client.py  —  cache + retry + log  (every call)  │
└──────────────────────────────────────────────────────────────────────┘
```

---

## The five ideas that shape everything

1. **Every claim must cite a source.** Grounding is mechanically enforced, not asked for in a prompt.
2. **Interpretation lives in `facts`. Raw source lives in `chunks`.** 
3. **LLM where judgment is needed. Deterministic where exactness matters.** Resolve merges semantically; OCR-repair fixes only the unambiguous; verifier checks structurally first, then semantically.
4. **Idempotent at every stage.** Re-running costs $0 (diskcache). Same output on the same input.
5. **Operator edits feed back into rules that enforce themselves.** Not few-shot prompting — durable, versioned, inspected by a verifier.

---

## Layer 1 — Storage

Two stores, two jobs.

### Postgres 16 + pgvector — 11 tables for structured data

| Group | Tables | Purpose |
|---|---|---|
| Inputs | `cases`, `documents`, `extractions` | the matter + uploaded docs + raw per-doc LLM output |
| Knowledge | `facts`, `fact_evidence` | canonical deduplicated facts + M:N citations |
| Retrieval | `chunks` | text snippets + 1536-dim embeddings |
| Outputs | `drafts`, `edits` | generated memos + operator corrections |
| Learning | `patterns`, `templates` | mined rules + versioned bundles |
| Observability | `llm_calls` | audit log for every model call |

### MinIO — original bytes, content-addressed

Every uploaded file lands at `cases/{case_id}/docs/{document_id}/{filename}`.
The `documents.storage_key` column is the pointer.

### Design note: two stores, on purpose

- `documents.raw_text` = **the extracted text** the pipeline uses (cheap to query, good enough for processing)
- MinIO = **the original file** (what users download, what re-OCR would re-read, what legal audit needs)

Lose `raw_text`? Re-OCR from MinIO. 

**Where to look:** [backend/app/db/tables.py](backend/app/db/tables.py), [backend/app/storage/minio_client.py](backend/app/storage/minio_client.py)

---

## Layer 2 — Ingestion

When a user uploads a file via `POST /api/cases/{id}/documents`:

```
1. Read bytes into memory
2. SHA256 → check if this exact file already exists for this case
     (skip everything below if yes — returns existing row)
3. Tiered OCR — extract_text(bytes, filename)
     ├── UTF-8 decodable → engine="text"
     ├── starts with %PDF- and has a text layer → engine="pdfplumber"
     ├── starts with %PDF- and sparse text → engine="tesseract"
     └── PNG/JPEG → engine="tesseract"
4. Classify the extracted text with GPT-4.1-mini
     → title_search | servicer_email | court_order | property_record | other
5. INSERT into documents (raw_text, doc_type, sha, meta.ocr, ...)
     → Postgres assigns doc.id
6. Upload the bytes to MinIO at cases/{case_id}/docs/{doc.id}/{filename}
7. UPDATE documents SET storage_key = that path
8. Return the document row with 201
```

### Design note: route by magic bytes, not file extension

A `.pdf` upload that's actually plain text gets treated as text. A `.txt` upload that's actually a PDF gets treated as a PDF. The router sniffs the first 8 bytes — `%PDF-`, `\x89PNG`, `\xff\xd8\xff` — instead of trusting the filename.

Trust input at your peril.

### Design note: tiered OCR, not one engine

Most legal PDFs (Word exports, form templates) have a text layer. `pdfplumber` reads them for free in milliseconds. Only image-only scans fall through to Tesseract (~1-3s/page). A future Vision tier can take over on low-confidence pages — the hook is there (`mean_confidence` is already captured), just not wired.

Concrete: on the example case pdf rendered as 4 image-only PDFs, Tesseract gets 94-96% mean confidence.

**Where to look:** [backend/app/api/documents.py](backend/app/api/documents.py), [backend/app/pipeline/ocr.py](backend/app/pipeline/ocr.py), [backend/app/pipeline/classify.py](backend/app/pipeline/classify.py)

---

## Layer 3 — Knowledge Graph

When a user calls `POST /api/cases/{id}/process`:

### 3a. OCR repair (deterministic regex)

Fixes only the unambiguous cases:
- `$445,OOO.OO → $445,000.00` (O inside $-prefixed numbers)
- `2O21-O123456 → 2021-0123456` (dashed numeric tokens)

Ambiguous cases (`T1TLE` → `TITLE`, `F1orida` → `Florida`) are left for the LLM extractor — context disambiguates.

**Writes `documents.cleaned_text`**. Original `raw_text` is preserved.

### 3b. Per-doc-type extraction (LLM)

One specialist extractor per doc type:

| doc_type | Extractor | What it pulls |
|---|---|---|
| `title_search` | `extract_title_search()` | liens, ownership chain, tax statuses |
| `servicer_email` | `extract_servicer_email()` | action items, payoff, transfer, attorney |
| `court_order` | `extract_court_order()` | deadlines, appearances, filing requirements |

Each sends `cleaned_text` (with `[L{n}]` line prefixes) to GPT-4.1 in strict-JSON mode. Returns a typed Pydantic tree where **every field carries `source_spans`** — the file + line numbers supporting it.

Writes to `extractions` — one JSONB row per document.

### 3c. Cross-doc resolver (LLM)

**One LLM call per `/process` run.** Reads all per-doc extractions for the case. Returns canonical, deduplicated facts — each one with evidence links back to the source spans.

Writes to `facts` + `fact_evidence` (M:N).

### Design note: LLM resolver, not regex

An earlier version hand-wrote entity normalization — strip `LLC` / `Inc.` / `N.A.` / `d/b/a`, lowercase, fingerprint-match. It worked on fixtures. It broke the moment a real case came in: typos (`Welss Fargo`), partial mentions (*"the mortgage"* referring to a specific record in another doc), entity-name variations (`Palmetto Bay Homeowners Association` vs the same + `, Inc.`).

Replaced with one LLM call. Trade-off: ~$0.005-0.015 per case (vs $0 for regex), cached on re-runs. **Gain: semantic robustness + conflict surfacing the regex couldn't do.**

### Design note: temporal handling (`previous_values`)

When the same fact appears at different timestamps (e.g., two servicer emails quoting different payoff amounts), the resolver prompt says *"latest wins — but preserve prior versions in a `previous_values` array"*.

Concrete example from case 1 with the 2-email test:

```
Before resolver:
  extraction 1 (email Mar 1):   payoff_update: {amount: 487920, as_of: Mar 1}
  extraction 2 (email Mar 22):  payoff_update: {amount: 490527.44, as_of: Mar 22}

After resolver — ONE canonical fact:
  {
    amount: "490527.44",
    as_of: "2026-03-22",
    previous_values: [{amount: "487920.00", as_of: "2026-03-01"}]
  }
  + 2 fact_evidence rows (one span per email)
```

The draft memo then says: *"Payoff updated from $487,920 (Mar 1) to $490,527.44 (Mar 22)"* with citations to **both** emails.

### Design note: two schemas per extractor

Each extractor has an **LLM-facing schema** (`str` dates, `str` amounts) and a **canonical stored schema** (`date`, `Decimal`). Why? OpenAI strict-JSON mode rejects `format: "date"` and is flaky on `Decimal`. Convert on the Python side.

Doubles the schemas; keeps both the LLM interface and the DB types clean.

### Design note: content-hash dedup_key

`dedup_key = sha256(fact_type + canonical_json(payload))[:32]`. Same LLM output → same hash → same DB row updated, not duplicated. Preserves idempotency without string-matching assumptions.

**Where to look:** [backend/app/pipeline/ocr_repair.py](backend/app/pipeline/ocr_repair.py), [backend/app/pipeline/extract/](backend/app/pipeline/extract/), [backend/app/pipeline/resolve.py](backend/app/pipeline/resolve.py)

---

## Layer 4 — Retrieval Index

Runs at the end of `/process`, parallel to the knowledge graph.

### 4a. Structural chunking

Break each document's `cleaned_text` at structural boundaries — blank lines, numbered items, section headers. Each chunk records `line_start` / `line_end` so citations later can point back precisely.

Never splits a numbered item mid-entry (a lien in Schedule B stays in one chunk).

### 4b. Embedding

Batch-embed all chunks via `text-embedding-3-small` (1536 dims). Store in `chunks.embedding` (pgvector `Vector(1536)` column).

An HNSW index (`m=16, ef_construction=64`) is pre-built for fast cosine-distance search.

### 4c. BM25 keyword index

In-memory, lazy, per-case. Built on first query. Hyphen-preserving tokenizer — so `2021-0123456` is one token, not three.

### Design note: BM25 + vector, because each catches what the other misses

| Query | BM25 | Vector |
|---|---|---|
| `2021-0123456` (exact instrument number) | ✅ perfect | ⚠️ may miss — rare token embeddings are noisy |
| "mortgage assignment" | ⚠️ exact-word only | ✅ finds "Assignment of Mortgage" paraphrased as "loan transfer" |
| "property taxes" | ✅ | ✅ |

Running both and merging with Reciprocal Rank Fusion gets the best of each.

**Where to look:** [backend/app/pipeline/chunk.py](backend/app/pipeline/chunk.py), [backend/app/pipeline/index.py](backend/app/pipeline/index.py), [backend/app/pipeline/bm25_store.py](backend/app/pipeline/bm25_store.py), [backend/app/pipeline/retrieve.py](backend/app/pipeline/retrieve.py)

---

## Layer 5 — Evidence Packs (the grounding contract)

When a user clicks Generate, for **each section** of the draft plan, build an Evidence Pack with 4 buckets:

### Bucket 1 · `structured_facts`

SQL pull from `facts` where `fact_type IN plan.fact_types`. Already deduplicated, already temporally resolved, already citation-linked via `fact_evidence`.

### Bucket 2 · `text_evidence`

Hybrid retrieval, 3 stages:
1. For each of the plan's query angles (e.g., `"mortgage liens"`, `"HOA lis pendens"`): run BM25 + vector → RRF merge → top-20 candidates
2. Apply `doc_type_filter` (e.g., only `title_search` chunks)
3. LLM reranker (GPT-4.1-mini) picks the best 5

### Bucket 3 · `known_gaps`

Explicit "we looked, found nothing" notes. If the plan expected facts of some type and none were found:

```
"No judgment facts found in case graph for section 'judgments'."
```

This is the **hallucination brake**. The generator prompt is told: if evidence is silent, abstain. So the draft writes *"No unsatisfied judgments identified in source materials"* instead of inventing one.

### Bucket 4 · `conflicts`

Resolver-flagged disagreements ("same entity, different name formatting" / "two different payoff amounts on the same date"). Passed through so the generator can hedge.

### Design note: gaps as a first-class output

Most RAG systems have two failure modes: hallucinate when no source exists, or silently drop the section. Gaps make absence **visible**. The draft becomes: *"No X identified in source materials (per title_search_page2.pdf:L31, which lists judgment search results as empty)."*

**Where to look:** [backend/app/pipeline/plans.py](backend/app/pipeline/plans.py), [backend/app/pipeline/evidence.py](backend/app/pipeline/evidence.py), [backend/app/pipeline/rerank.py](backend/app/pipeline/rerank.py)

---

## Layer 6 — Grounded Generation

Each section: Generator → Verifier → (Retry on fail) → Save.

### 6a. Generator

**Input:** Evidence Pack (4 buckets) + case context + active learned patterns.
**LLM:** GPT-4.1, strict-JSON mode with `response_format=DraftSection`.
**Output:** a typed Pydantic tree — section → blocks → fields → citations → source spans.

The 8-rule system prompt (abbreviated):
1. Every claim must be grounded in the evidence pack
2. Every block must have ≥1 citation
3. Never invent; if evidence is silent → abstain
4. Preserve precision (exact amounts, dates, instrument numbers)
5. Use badges for status (`URGENT`, `ACTION REQUIRED`, `DELINQUENT`, etc.)
6. Fields is a list of `{key, value}` — short, scannable
7. Obey any LEARNED_RULES injected from patterns
8. When payload has `previous_values` → surface the change + cite both spans

### 6b. Verifier (two passes)

**Pass 1 — deterministic (Python):**
- Every block has at least one citation?
- Every citation has at least one span?
- Every cited file is in the evidence pack's allowed-files set?

**Pass 2 — LLM grounding (GPT-4.1-mini):**
- Extract every factual claim in the section
- For each, decide `supported: true/false` against the evidence pack
- Check `LEARNED_RULES` compliance
- Return lists of `unsupported_claims` + `rule_violations`

### 6c. Retry loop

If either pass fails, regenerate **with the rejection attached** to the prompt:

```
CORRECTION REQUIRED (your previous output was rejected):
  - Unsupported claim: "$500,000 payoff" — no source cites this amount

Regenerate this section fixing the issues above.
```

Max 2 retries. After that, best-effort section is kept with a log note.

### Design note: grounding is mechanical, not a vibe

The difference between "RAG-ish" and "actually grounded" is the verifier. Every section has to pass both passes before it's saved. An LLM that writes a hallucinated amount will be caught by the LLM verifier (*"no source cites $500,000"*) and regenerated. The draft in the DB is the one that passed.

### Design note: structured output over prose

The LLM is forced to return a typed tree, not free-form markdown. Why? Parsing prose for citations is fragile (regex over markdown breaks). Parsing structured output is just `response_format=PydanticModel`. The renderer turns the typed tree into markdown deterministically afterwards.

**Where to look:** [backend/app/pipeline/generate/base.py](backend/app/pipeline/generate/base.py), [backend/app/pipeline/generate/verify.py](backend/app/pipeline/generate/verify.py), [backend/app/pipeline/generate/render.py](backend/app/pipeline/generate/render.py)

---

## Layer 7 — The Learning Loop

### 7a. Edit capture

An operator edits a draft (via the UI or via `sample_edits.json` fixture). The edited `DraftContent` + a structured diff get written to the `edits` table, linked to the original `draft_id`.

### 7b. Diff → classify (slow path, UI-submitted edits)

- `diff_drafts()` — LLM compares the original draft + the edit, returns a structured change list
- `classify_signals()` — labels each change as:
  - `fix` — system got a fact wrong (extractor needs improving; not generalizable)
  - `rule` — a reusable preference worth learning
  - `case_specific` — one-off detail (not generalizable)

Only `rule`-class signals move forward.

### 7c. Miner (LLM)

Groups all rule signals by draft_type. One LLM call per type. Prompt: *"generalize these into durable rules."* Returns `MinedPattern[]`:

```
Signals (14 from sample_edits.json):
[0] "operator added instrument_number to the Wells Fargo block"
[1] "operator added instrument_number to the HOA block"
[2] "operator added 'ACTION REQUIRED' badge to the HOA block"
[3] ...

Generalized into 5 patterns:
  Pattern A: WHEN section addresses liens
             → MUST include instrument_number on every lien
  Pattern B: WHEN lien is lis_pendens
             → MUST add ACTION REQUIRED badge
  Pattern C: ...
```

### 7d. Write

- **Upsert to `patterns`** — if exists, reinforce confidence; else insert new row
- **Bump `templates`** — new row with incremented version; previous template deactivated

### 7e. Enforcement

On the **next** generation call:
- `active_patterns()` pulls rules matching `(draft_type, section_id)` and injects them as `LEARNED_RULES` in the generator's system prompt
- The verifier's LLM pass is told to also check `rule_violations` — any rule violated → section rejected → regenerate

Result: v2 drafts reflect the mined rules at generation time; the verifier rejects sections that violate them.

### Design note: fast path + slow path

`sample_edits.json` (the fixture) has a pre-annotated `key_edits` array — each entry is already labeled as a rule signal. The miner reads these directly, skipping diff + classify.

UI-submitted edits don't have that annotation. They go through the full pipeline: diff (LLM) → classify (LLM) → filter to rule-class → mine (LLM). Same output shape; more LLM calls + higher latency.

Both paths feed the same miner. Real-world edits use the slow path.

### Design note: measured improvement

On the Rodriguez case, rule-compliance on the Title Review Summary:
- **v1 (baseline, no patterns)**: 0.60 (6/10 rules satisfied)
- **v2 (after mining 2 operator edits)**: 0.90 (9/10 rules satisfied)
- **Δ = +0.30**

Grounded-claim coverage, citation accuracy, and hallucination rate stay saturated (0.90-1.00) on both v1 and v2 — the evidence-pack + verifier layer already enforces those. Rule compliance is the metric the learning loop moves.

### Design note: templates as audit trail

Every mining run bumps the template version, deactivating the previous one. Every draft pins its `template_version` at creation time. So a draft created against v1 stays interpretable as "what the system would produce with v1's rules," even after v5 is active.

**Where to look:** [backend/app/learning/](backend/app/learning/), [outputs/evaluation.md](outputs/evaluation.md), [outputs/patterns.yaml](outputs/patterns.yaml)

---

## Cross-cutting — the LLM wrapper

Every LLM call in the system — classify, extract, resolve, rerank, generate, verify, diff, classify-edit, mine — goes through one function.

```python
async def parse(*, purpose, model, messages, response_format, case_id) -> T:
    1. hash = SHA256(model + messages + schema)
    2. if hash in diskcache → return cached object, log row with cache_hit=true
    3. else:
         completion = await client.chat.completions.parse(...)
         cache the result
         log row with tokens / cost / latency
         return parsed Pydantic object
    4. on rate-limit / 5xx / network: retry (tenacity, exponential backoff, 4 attempts)
    5. on any failure: log row with success=false, re-raise
```

### What this buys you
- **Free re-runs.** Same input → cache hit → $0, 2ms latency.
- **Single point of control.** Swap models, add rate limiting, change providers — one file.
- **Full audit.** `llm_calls` table has a row per invocation: case_id, purpose, model, tokens, cost, latency, cache_hit, success.

**Where to look:** [backend/app/llm/client.py](backend/app/llm/client.py)

---

## Concrete trace — a document through the whole system

Actual data from a fresh run of case 1 (Rodriguez):

```
  Upload of 4 scanned PDFs (court_order, servicer_email, 2 × title_search)
    → Tesseract OCR, 94-96% mean confidence per file
    → classified (court_order / servicer_email / title_search × 2)
    → MinIO blobs at cases/1/docs/{1..4}/*.pdf

  POST /api/cases/1/process   (51s, ~$0.07)
    Step 1: OCR-repair → 0 money fixes, 0 instrument fixes (text was clean)
    Step 2: 4 extractions written (one per doc) — ~12 KB of structured payloads total
    Step 3: Resolver LLM call → 22 canonical facts, 1 conflict (HOA name formatting)
    Step 4: 15 chunks chunked, all embedded via text-embedding-3-small

  POST /api/cases/1/drafts {draft_type: title_review_summary}   (117s, ~$0.08)
    For each of 4 sections (liens / tax_status / ownership / judgments):
      → build evidence pack (SQL facts + hybrid retrieval + rerank)
      → generate DraftSection (GPT-4.1, typed output)
      → verify (deterministic + LLM grounding) — all passed
    Final draft: 14 blocks, 0 abstentions, every claim cited

  Draft viewer at /cases/1/drafts/1 — click any citation chip,
  source panel highlights the exact lines from the original PDF.
```


---

## Reading order for someone new to this code

1. **[README.md](README.md)** — setup + demo commands
2. **This file** — architecture overview
3. **[explained/all_the_tables.md](explained/all_the_tables.md)** — every DB table, in plain English
4. **[explained/file_upload_explained.md](explained/file_upload_explained.md)** — step-1 deep dive
5. **[backend/app/pipeline/process.py](backend/app/pipeline/process.py)** — the orchestrator; reading top-to-bottom shows the whole pipeline in ~100 lines
6. **[outputs/evaluation.md](outputs/evaluation.md)** — the v1-vs-v2 metrics table

Each layer's `Where to look` section points at the 1-3 files that own that layer's logic.

---

## The short version (if you skimmed)

> Messy docs land in **MinIO** (originals) + **Postgres** (extracted text + metadata).
> A tiered **OCR** step handles scans. **Per-doc-type LLM extractors** pull structured facts with citations.
> A **cross-doc resolver LLM call** merges duplicates and handles temporal updates.
> In parallel, text is **chunked and embedded** for hybrid search.
> On draft generation, each section builds an **Evidence Pack** (facts + top-5 chunks + gaps + conflicts), feeds it to a **Generator LLM**, and a **Verifier** rejects anything ungrounded — retry up to 2x.
> When an operator edits a draft, a **diff → classify → mine** pipeline extracts durable rules, bumps a template version, and the **next draft's verifier enforces the new rules**. Measured +0.30 rule compliance.
> Everything routes through **one LLM wrapper** — cache, retry, log — so costs are predictable and re-runs are free.

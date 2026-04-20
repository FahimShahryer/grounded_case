# Architecture (short)

Messy legal documents in → cited drafts out → the system improves when operators edit.

```
1. STORAGE        Postgres (11 tables) + pgvector  |  MinIO (originals)
2. INGESTION      bytes → SHA dedup → tiered OCR → classify → row + blob
3. KNOWLEDGE      OCR-repair → per-doc LLM extractors → LLM resolver → facts + evidence
4. RETRIEVAL      chunks → pgvector HNSW + BM25 (hybrid)
5. EVIDENCE PACK  structured_facts + text_evidence + gaps + conflicts  (per section)
6. GENERATION     Generator (typed output) → Verifier (determ + LLM) → retry ≤2x
7. LEARNING       edit → diff → classify → mine → pattern → template bump
    cross-cutting: llm/client.py — cache + retry + log on every call
```

## Whole-system diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                          INGESTION — per uploaded file                        │
│                                                                               │
│   User upload                                                                 │
│   POST /api/cases/{id}/documents                                              │
│         │                                                                     │
│         ▼                                                                     │
│   SHA256 dedup  (skip if file already in case)                                │
│         │                                                                     │
│         ▼                                                                     │
│   TIERED OCR  (magic-byte routing)                                            │
│   ├─ text            (UTF-8 decodable)                                        │
│   ├─ pdfplumber      (%PDF- w/ text layer)                                    │
│   └─ tesseract       (image-only PDF / PNG / JPG — mean_confidence captured)  │
│         │                                                                     │
│         ▼                                                                     │
│   Classify  (GPT-4.1-mini)                                                    │
│   title_search | servicer_email | court_order | property_record | other       │
│         │                                                                     │
│         ▼                                                                     │
│   ┌──────────────────────┐        ┌────────────────────────────────┐          │
│   │ documents row        │◄──────►│ MinIO blob                     │          │
│   │ raw_text, doc_type   │  key   │ cases/{id}/docs/{doc_id}/file  │          │
│   └──────────┬───────────┘        └────────────────────────────────┘          │
└──────────────┼───────────────────────────────────────────────────────────────┘
               │
               ▼ POST /api/cases/{id}/process
┌──────────────────────────────────────────────────────────────────────────────┐
│                            KNOWLEDGE + RETRIEVAL                              │
│                                                                               │
│                       OCR repair (regex, unambiguous only)                    │
│                       → documents.cleaned_text                                │
│                                 │                                             │
│              ┌──────────────────┴───────────────────┐                         │
│              ▼ (knowledge graph)           (retrieval — parallel) ▼           │
│                                                                               │
│   Per-doc LLM extractors                   Structural chunking                │
│   title_search / servicer_email /          (blank lines / numbered /         │
│   court_order  —  GPT-4.1 strict-JSON      headers; line_start, line_end)     │
│   every field has source_spans                       │                        │
│              │                                       ▼                        │
│              ▼                              Embed (1536d) → pgvector HNSW     │
│   ┌──────────────────────┐                  + BM25 (in-memory, lazy/case)     │
│   │ extractions          │                          │                         │
│   │ 1 JSONB row per doc  │                          ▼                         │
│   └──────────┬───────────┘                  ┌──────────────┐                  │
│              ▼                              │    chunks    │                  │
│   Cross-doc resolver (1 LLM call)           └──────┬───────┘                  │
│   semantic merge + temporal                        │                          │
│   (previous_values[])                              │                          │
│              │                                     │                          │
│              ▼                                     │                          │
│   ┌──────────────────────┐                         │                          │
│   │ facts                │                         │                          │
│   │ fact_evidence (M:N)  │                         │                          │
│   └──────────┬───────────┘                         │                          │
│              └──────────────────┬──────────────────┘                          │
└─────────────────────────────────┼────────────────────────────────────────────┘
                                  │
                                  ▼ POST /api/cases/{id}/drafts
┌──────────────────────────────────────────────────────────────────────────────┐
│                     EVIDENCE PACK + GROUNDED GENERATION                       │
│                                                                               │
│                Plan: sections + fact_types + query angles                     │
│                                 │                                             │
│                                 ▼                                             │
│   ┌───────────────────────────────────────────────────────────────┐           │
│   │              EVIDENCE PACK (built per section)                │           │
│   │  ┌──────────────┐  ┌──────────────┐  ┌─────────┐  ┌─────────┐ │           │
│   │  │ structured_  │  │  text_       │  │ known_  │  │conflicts│ │           │
│   │  │   facts      │  │  evidence    │  │  gaps   │  │         │ │           │
│   │  │ (SQL facts)  │  │ BM25+vec →   │  │(halluc. │  │(resolver│ │           │
│   │  │              │  │ RRF → rerank │  │ brake)  │  │ flagged)│ │           │
│   │  └──────┬───────┘  └──────┬───────┘  └────┬────┘  └────┬────┘ │           │
│   └─────────┼──────────────── │ ──────────────┼────────────┼──────┘           │
│             └────────┬────────┴───────────────┴────────────┘                  │
│                      ▼                                                        │
│          ┌─────────────────────────┐      ┌──────────────────────┐            │
│          │ GENERATOR (GPT-4.1)     │◄─────│ active patterns      │            │
│          │ strict-JSON             │      │ (LEARNED_RULES)      │            │
│          │ DraftSection: blocks →  │      └──────────────────────┘            │
│          │ fields → citations      │                                          │
│          └────────────┬────────────┘                                          │
│                       ▼                                                       │
│          ┌─────────────────────────┐                                          │
│          │ VERIFIER P1 (Python)    │ ─── fail ──┐                             │
│          │ blocks cited? files ok? │            │                             │
│          └────────────┬────────────┘            │                             │
│                       ▼ pass                    ▼                             │
│          ┌─────────────────────────┐   ┌────────────────────┐                 │
│          │ VERIFIER P2 (GPT-mini)  │──►│ Regenerate with    │                 │
│          │ claim grounding +       │fail│ rejection (≤ 2x)   │                 │
│          │ rule_violations         │   └────────┬───────────┘                 │
│          └────────────┬────────────┘            │                             │
│                       ▼ pass                    │                             │
│          ┌─────────────────────────┐            │                             │
│          │ Section approved →      │◄───────────┘                             │
│          │ render markdown →       │                                          │
│          │ drafts row (pins        │                                          │
│          │ template_version)       │                                          │
│          └────────────┬────────────┘                                          │
└───────────────────────┼──────────────────────────────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                              LEARNING LOOP                                    │
│                                                                               │
│   Operator edits draft                                                        │
│          │                                                                    │
│          ▼                                                                    │
│   diff_drafts (LLM)  →  classify_signals  →  keep only `rule`-class           │
│   (drop `fix` = extractor bug, drop `case_specific` = one-off detail)         │
│          │                                                                    │
│          ▼                                                                    │
│   Miner (LLM, per draft_type) — generalize into MinedPattern[]                │
│          │                                                                    │
│          ▼                                                                    │
│   patterns upsert  +  templates bump  ─── feeds next generation ──┐           │
│                                                                   │           │
│                                   ▲                               │           │
│                                   └───── LEARNED_RULES ◄──────────┘           │
│                                         (into generator + verifier)           │
└──────────────────────────────────────────────────────────────────────────────┘

  cross-cutting · every LLM call (classify, extract, resolve, rerank, generate,
  verify, diff, classify-edit, mine) routes through llm/client.py parse():
  SHA256 cache · tenacity retry · llm_calls audit (tokens, cost, latency,
  cache_hit, success).
```

## Five ideas that shape everything

1. **Every claim must cite a source.** Grounding is mechanically enforced.
2. **Interpretation lives in `facts`; raw source lives in `chunks`.**
3. **LLM where judgment is needed, deterministic where exactness matters.**
4. **Idempotent everywhere.** Re-running costs $0 (diskcache).
5. **Operator edits become rules the verifier enforces** — durable, versioned.

---

## Layer 1 — Storage

- **Postgres + pgvector (11 tables):** `cases`, `documents`, `extractions`, `facts`, `fact_evidence`, `chunks`, `drafts`, `edits`, `patterns`, `templates`, `llm_calls`.
- **MinIO:** content-addressed original bytes at `cases/{case_id}/docs/{document_id}/{filename}`. `documents.storage_key` points to it.
- `documents.raw_text` is the pipeline input; MinIO is the source of truth. Lose one, rebuild from the other.

---

## Layer 2 — Ingestion (`POST /api/cases/{id}/documents`)

`bytes → SHA dedup → tiered OCR → classify → insert row → upload to MinIO → set storage_key`.

- **Magic-byte routing** (not extension): `%PDF-` / `\x89PNG` / UTF-8 sniff → `text` | `pdfplumber` | `tesseract`.
- **Tiered OCR:** pdfplumber first (ms, free), Tesseract only on image-only PDFs (~94–96% confidence on the fixture scans). Vision tier hook is there (`mean_confidence` captured), not wired.
- Classifier (GPT-4.1-mini) assigns `title_search | servicer_email | court_order | property_record | other`.

---

## Layer 3 — Knowledge Graph (`POST /api/cases/{id}/process`)

1. **OCR repair** — deterministic regex fixes only the unambiguous (`$445,OOO.OO → $445,000.00`, `2O21-O123456 → 2021-0123456`). Writes `cleaned_text`; ambiguous stuff (`T1TLE`) is left for the LLM.
2. **Per-doc-type extractors** — one specialist each (`title_search` / `servicer_email` / `court_order`). GPT-4.1 strict-JSON on `cleaned_text` with `[L{n}]` line prefixes; every field carries `source_spans`. One JSONB row per doc in `extractions`.
3. **Cross-doc resolver** — one LLM call per `/process` that merges all extractions into canonical facts + evidence links. Replaces earlier regex normalization — handles typos, partial references, entity-name variation.
4. **Temporal handling** — resolver keeps the latest value and stores prior ones in `previous_values[]`; the draft surfaces the change citing both spans.
5. **Schemas are doubled** — LLM-facing (`str` dates/amounts) vs canonical stored (`date`, `Decimal`). OpenAI strict-JSON rejects `format: "date"`.
6. **`dedup_key = sha256(fact_type + canonical_json(payload))[:32]`** — same output updates, not duplicates.

---

## Layer 4 — Retrieval Index

Runs parallel to the graph during `/process`.

- **Structural chunking** — split on blank lines / numbered items / headers; `line_start`/`line_end` preserved. Never splits a numbered lien entry.
- **Embedding** — `text-embedding-3-small` (1536 dims) into `chunks.embedding`; HNSW `m=16, ef_construction=64`.
- **BM25** — in-memory, lazy per case, hyphen-preserving tokenizer (`2021-0123456` is one token).
- **Why both:** BM25 nails exact tokens; vectors catch paraphrase. RRF merges them.

---

## Layer 5 — Evidence Pack (per section, 4 buckets)

1. **structured_facts** — SQL pull from `facts` (already deduped + temporally resolved + citation-linked).
2. **text_evidence** — per plan-query: BM25 + vector → RRF → top-20 → doc-type filter → LLM reranker → top 5.
3. **known_gaps** — "we looked, found nothing" notes. The **hallucination brake**: the generator abstains instead of inventing.
4. **conflicts** — resolver-flagged disagreements, passed through so the generator can hedge.

---

## Layer 6 — Grounded Generation

Per section: **Generator → Verifier → retry (≤2) → save**.

- **Generator:** GPT-4.1 strict-JSON, `response_format=DraftSection`. Typed tree — section → blocks → fields → citations → spans. 8-rule prompt (grounding, ≥1 citation/block, abstain-if-silent, preserve precision, badges, LEARNED_RULES, `previous_values` surfacing).
- **Verifier pass 1 (Python):** every block has a citation, every citation has a span, every cited file is in the evidence pack.
- **Verifier pass 2 (GPT-4.1-mini):** extract claims → check `supported` against evidence + `LEARNED_RULES`. Returns `unsupported_claims` + `rule_violations`.
- **Retry loop:** regenerate with the rejection attached to the prompt; max 2 attempts, then best-effort with a log note.
- **Why structured output over prose:** parsing markdown for citations is fragile; parsing `response_format=PydanticModel` is not.

---

## Layer 7 — Learning Loop

- **Capture:** operator edit → `edits` row with structured diff.
- **Slow path (UI edits):** `diff_drafts` (LLM) → `classify_signals` → keep only `rule`-class (drop `fix` / `case_specific`).
- **Fast path:** `sample_edits.json` arrives pre-annotated with `key_edits`; skips diff + classify.
- **Miner (LLM):** groups rule signals by `draft_type`, generalizes into `MinedPattern[]`.
- **Write:** upsert `patterns` (reinforce confidence if exists); bump `templates` (new version, previous deactivated).
- **Enforce:** next generation call injects `active_patterns(draft_type, section_id)` as `LEARNED_RULES`; verifier rejects sections that violate them.

**Measured on Rodriguez:** rule-compliance on Title Review Summary **0.60 → 0.90 (+0.30)** after mining 2 edits. Grounded-claim coverage / citation accuracy / hallucination rate stay saturated on both v1 and v2 — those are already enforced by the evidence pack + verifier.

---

## Cross-cutting — the LLM wrapper

Every call (classify, extract, resolve, rerank, generate, verify, diff, classify-edit, mine) goes through `parse()`:

- SHA256 over `(model + messages + schema)` → diskcache hit → $0, 2ms.
- Tenacity retry (exponential, 4 attempts) on rate-limit / 5xx / network.
- Audit row per invocation in `llm_calls` (case_id, purpose, tokens, cost, latency, cache_hit, success).

---


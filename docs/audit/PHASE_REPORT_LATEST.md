# Phase 3 Completion Report — RAG Pipeline

**Date:** 2026-04-13
**Phase:** 3 — Retrieval-Augmented Generation Pipeline
**Status:** COMPLETE
**Baseline:** 32 pass → 48 pass (+16), 4 skip → 12 skip (+8)

---

## What Was Built

Phase 3 added the full RAG (Retrieval-Augmented Generation) pipeline to Dream Motif Interpreter. Before this phase, the system could segment dream journal entries, extract themes using an LLM, and rank them by salience — but had no way to search across the archive or retrieve relevant past dreams for context.

### T10 — RAG Ingestion Pipeline

The ingestion pipeline takes a dream entry and produces searchable vector chunks. Each entry is tokenized using tiktoken (the same tokenizer family as OpenAI's embedding models), split at paragraph boundaries when it exceeds 512 tokens with 50-token overlap, then embedded using OpenAI `text-embedding-3-small` (1536-dimensional vectors) and stored in PostgreSQL via `pgvector`. The unique constraint on `(dream_id, chunk_index)` makes indexing fully idempotent — running it twice produces the same number of rows.

Two P1 findings were discovered in the post-T10 deep review and fixed immediately: the OpenAI embedding client had no HTTP error handling (`EmbeddingServiceError` added), and the token counter was using word count instead of real tiktoken tokens (replaced with `cl100k_base` encoder).

### T11 — RAG Query Pipeline

The query pipeline accepts a text query, embeds it, and executes a hybrid search combining pgvector cosine similarity with PostgreSQL full-text search. The two result sets are fused using Reciprocal Rank Fusion (RRF: `score = 1/(60 + rank_cosine) + 1/(60 + rank_fts)`), then filtered by a relevance threshold of 0.35. Results below the threshold — or an empty query — return an `InsufficientEvidence` dataclass (not an exception).

The pre-T11 mandatory patch (ARCH-2) added migration `006_add_hnsw_index.py`, creating an HNSW index on `dream_chunks.embedding` using `autocommit_block()` to run `CREATE INDEX CONCURRENTLY` outside a transaction.

One P1 was found and immediately fixed: `query.py`'s embedding client also had no HTTP error handling (`QueryEmbeddingError` added).

### T12 — Retrieval Evaluation Baseline

The evaluation script (`scripts/eval.py`) seeds a 20-entry synthetic dream corpus, runs 10 queries covering all four query types (simple, multi-doc, multi-hop, no-answer), and records hit@3, MRR, and no-answer accuracy in `docs/retrieval_eval.md`. The script uses stub (zero-vector) embeddings when `OPENAI_API_KEY` is absent or starts with `test-`, so the evaluation is runnable locally without a real API key.

Synthetic baseline: `hit@3 = 1.00`, `MRR = 1.00`, `no-answer accuracy = 1.00`.

---

## Test Delta

| Milestone | Passing | Skipped |
|-----------|---------|---------|
| Phase 2 end (T09) | 32 | 4 |
| T10 + FIX-C3 | 41 | 6 |
| T11 + FIX-C4 | 46 | 10 |
| T12 (Phase 3 end) | 48 | 12 |

The 12 skipped tests require a real `OPENAI_API_KEY` (non-`test-`) for live embedding calls.

---

## Open Findings at Phase 3 Boundary

**P1 — 1 open (FIX-C5-1)**
- **CODE-33**: Dead `except HTTPError` branch in `embed()` in both `ingestion.py` and `query.py` — unreachable since sync helper already converts the error type.

**P2 — 7 open**
- **FIX-C5-2**: 4 aging items (CODE-2, CODE-5, CODE-11, CODE-12) — 4+ cycles without fix window; must close before T13 DONE.
- **CODE-34**: `health.py` bare `except Exception` without logging.
- **CODE-38**: `tests/unit/test_config.py` absent.
- **CODE-39**: `retrieval_eval.md §Answer Quality Metrics` no completed run.
- **CODE-32**: Duplicate `OpenAIEmbeddingClient` in ingestion/query modules.

---

## Health Verdict: OK

No P0s. One P1 is dead-code removal with no logic change. Zero stop-ship conditions. RAG pipeline functionally complete.

---

## Next Phase: Phase 4 — API Layer and Workers

Begins with FIX-C5-1 + FIX-C5-2, then T13 (Health Endpoint and Observability).
Phase gate: documented HTTP API, background workers, full end-to-end flow from ingest to searchable archive.

# Task Graph — Dream Motif Interpreter

Version: 1.0
Last updated: 2026-04-10

---

## Phase 1: Foundation

Goal: Working project skeleton with CI, a smoke test suite, a complete database schema, and a Google Docs ingestion client. No feature logic yet — just the load-bearing infrastructure that all subsequent tasks depend on.

Phase gate: CI green; 0 ruff violations; DB migrations apply cleanly; smoke tests pass; GDocs client authenticated and returning raw document text in integration test.

---

## T01: Project Skeleton

Owner:      codex
Phase:      1
Type:       none
Depends-On: none

Objective: |
  Create the complete project skeleton: directory structure, package configuration,
  app factory, shared config, shared tracing module, and entry point. The application
  must start without errors given valid environment variables.

Acceptance-Criteria:
  - id: AC-1
    description: "`python -m app.main` starts the FastAPI app without import errors when all required env vars are set. Verified by tests/unit/test_smoke.py::test_app_starts."
    test: "tests/unit/test_smoke.py::test_app_starts"
  - id: AC-2
    description: "`app/shared/config.py::Settings` raises `ValidationError` when `DATABASE_URL` is absent. Verified by tests/unit/test_smoke.py::test_config_fails_fast_on_missing_database_url."
    test: "tests/unit/test_smoke.py::test_config_fails_fast_on_missing_database_url"
  - id: AC-3
    description: "`app/shared/tracing.py::get_tracer()` returns a tracer instance without error; calling it twice returns the same tracer type. Verified by tests/unit/test_smoke.py::test_tracer_singleton."
    test: "tests/unit/test_smoke.py::test_tracer_singleton"

Files:
  - app/__init__.py
  - app/main.py
  - app/api/__init__.py
  - app/api/health.py
  - app/services/__init__.py
  - app/llm/__init__.py
  - app/retrieval/__init__.py
  - app/models/__init__.py
  - app/workers/__init__.py
  - app/shared/__init__.py
  - app/shared/config.py
  - app/shared/tracing.py
  - pyproject.toml
  - requirements.txt
  - requirements-dev.txt
  - tests/__init__.py
  - tests/conftest.py
  - tests/unit/__init__.py
  - tests/unit/test_smoke.py

Notes: |
  `app/shared/config.py` uses Pydantic BaseSettings. All required vars listed in
  docs/ARCHITECTURE.md §Runtime Contract must be declared with no default.
  `app/shared/tracing.py` wraps OpenTelemetry; in v1 uses a noop exporter.
  `app/main.py` creates the FastAPI app, registers the health router, and nothing else yet.

---

## T02: CI Setup

Owner:      codex
Phase:      1
Type:       none
Depends-On: T01

Objective: |
  Configure GitHub Actions CI to run on every push and pull request: install dependencies,
  run ruff lint, ruff format check, and pytest. CI must pass before T03 begins.

Acceptance-Criteria:
  - id: AC-1
    description: "`.github/workflows/ci.yml` exists and contains jobs for: install, ruff-check, ruff-format, pytest. Verified by tests/unit/test_ci.py::test_ci_workflow_has_required_jobs."
    test: "tests/unit/test_ci.py::test_ci_workflow_has_required_jobs"
  - id: AC-2
    description: "`ruff check app/ tests/` exits 0 with the project skeleton in place. Verified by tests/unit/test_ci.py::test_ruff_check_passes."
    test: "tests/unit/test_ci.py::test_ruff_check_passes"

Files:
  - .github/workflows/ci.yml
  - tests/unit/test_ci.py

Notes: |
  CI uses Python 3.11. No DB service block needed yet (T04 adds migrations).
  The pytest step must set all required env vars to test values (not real credentials).

---

## T03: Smoke Tests

Owner:      codex
Phase:      1
Type:       none
Depends-On: T01, T02

Objective: |
  Add a smoke test suite that verifies the application can start, the health endpoint
  returns 200, and the config validation catches missing required variables.

Acceptance-Criteria:
  - id: AC-1
    description: "`GET /health` returns HTTP 200 with body `{\"status\": \"ok\"}` when the app is running. Verified by tests/integration/test_health.py::test_health_endpoint_returns_200."
    test: "tests/integration/test_health.py::test_health_endpoint_returns_200"
  - id: AC-2
    description: "`GET /health` does not require authentication (no auth header needed). Verified by tests/integration/test_health.py::test_health_endpoint_no_auth_required."
    test: "tests/integration/test_health.py::test_health_endpoint_no_auth_required"
  - id: AC-3
    description: "`GET /health` returns the `index_last_updated` field (may be null before first sync). Verified by tests/integration/test_health.py::test_health_endpoint_includes_index_timestamp."
    test: "tests/integration/test_health.py::test_health_endpoint_includes_index_timestamp"

Files:
  - tests/integration/__init__.py
  - tests/integration/test_health.py

Notes: |
  Integration tests use pytest-asyncio with the FastAPI TestClient.
  The health endpoint must not log PII, must not count toward rate limits,
  and must not require authentication — these are enforced by IMPLEMENTATION_CONTRACT.md OBS-3.

---

## T04: Database Schema — Dream Entries, Taxonomy, Annotations

Owner:      codex
Phase:      1
Type:       none
Depends-On: T01

Objective: |
  Define and migrate the full database schema: dream entries, dream chunks (with pgvector),
  theme categories, dream-theme junction, and annotation version history. All migrations
  apply cleanly to a fresh PostgreSQL 16 + pgvector database.

Acceptance-Criteria:
  - id: AC-1
    description: "`alembic upgrade head` completes without error on a fresh database. Verified by tests/integration/test_migrations.py::test_migrations_apply_cleanly."
    test: "tests/integration/test_migrations.py::test_migrations_apply_cleanly"
  - id: AC-2
    description: "`dream_entries` table has columns: `id` (UUID PK), `source_doc_id`, `date`, `title`, `raw_text`, `word_count`, `content_hash`, `segmentation_confidence`, `created_at`. Verified by tests/integration/test_migrations.py::test_dream_entries_schema."
    test: "tests/integration/test_migrations.py::test_dream_entries_schema"
  - id: AC-3
    description: "`dream_chunks` table has columns: `id`, `dream_id` (FK), `chunk_index`, `chunk_text`, `embedding` (vector(1536)), `created_at`. Verified by tests/integration/test_migrations.py::test_dream_chunks_schema."
    test: "tests/integration/test_migrations.py::test_dream_chunks_schema"
  - id: AC-4
    description: "`theme_categories` table has columns: `id`, `name`, `description`, `status` (`suggested`/`active`/`deprecated`), `created_at`. `dream_themes` table has: `id`, `dream_id`, `category_id`, `salience`, `status`, `match_type`, `fragments` (JSONB), `created_at`. Verified by tests/integration/test_migrations.py::test_theme_schema."
    test: "tests/integration/test_migrations.py::test_theme_schema"
  - id: AC-5
    description: "`annotation_versions` table has columns: `id`, `entity_type`, `entity_id`, `snapshot` (JSONB), `changed_by`, `created_at`. Verified by tests/integration/test_migrations.py::test_annotation_versions_schema."
    test: "tests/integration/test_migrations.py::test_annotation_versions_schema"

Files:
  - alembic/env.py
  - alembic/versions/001_initial_schema.py
  - app/models/dream.py
  - app/models/theme.py
  - app/models/annotation.py
  - tests/integration/test_migrations.py

Notes: |
  pgvector extension must be enabled before the first migration: `CREATE EXTENSION IF NOT EXISTS vector`.
  Include this in the first migration file.
  All foreign keys use CASCADE on delete where appropriate (dream deleted → chunks deleted).
  Use UUIDs (gen_random_uuid()) for all primary keys.

---

## T05: Google Docs Ingestion Client

Owner:      codex
Phase:      1
Type:       none
Depends-On: T01

Objective: |
  Implement the Google Docs API client that authenticates via OAuth2 (refresh token flow)
  and retrieves the raw text and paragraph structure of the configured document.

Acceptance-Criteria:
  - id: AC-1
    description: "`GDocsClient.fetch_document()` returns a list of paragraphs when called with a valid `GOOGLE_DOC_ID` and valid OAuth credentials in a live integration test. Verified by tests/integration/test_gdocs_client.py::test_fetch_document_returns_paragraphs (marked skip if GOOGLE credentials absent)."
    test: "tests/integration/test_gdocs_client.py::test_fetch_document_returns_paragraphs"
  - id: AC-2
    description: "`GDocsClient.fetch_document()` raises `GDocsAuthError` when `GOOGLE_REFRESH_TOKEN` is invalid. Verified by tests/unit/test_gdocs_client.py::test_fetch_document_raises_on_invalid_token."
    test: "tests/unit/test_gdocs_client.py::test_fetch_document_raises_on_invalid_token"
  - id: AC-3
    description: "No OAuth credentials appear in log output when `GDocsClient.fetch_document()` is called. Verified by tests/unit/test_gdocs_client.py::test_no_credentials_in_logs."
    test: "tests/unit/test_gdocs_client.py::test_no_credentials_in_logs"

Files:
  - app/services/gdocs_client.py
  - tests/unit/test_gdocs_client.py
  - tests/integration/test_gdocs_client.py

Notes: |
  Use `google-auth` and `googleapiclient` packages. Store no credentials in source.
  The client reads `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN`,
  and `GOOGLE_DOC_ID` from `app/shared/config.py::Settings`.
  Integration test is marked `@pytest.mark.skipif(not os.getenv("GOOGLE_REFRESH_TOKEN"), ...)`.

---

## Fix Tasks — Cycle 3 (resolve before T10 DONE gate)

---

## FIX-C3-1: Add HTTP Error Handling to `OpenAIEmbeddingClient.embed()`

Owner:      codex
Phase:      3
Type:       fix
Depends-On: T10
Finding:    CODE-19 [P1]

Objective: |
  Wrap `urllib.request.urlopen()` in `_send_embedding_request()` with a
  `try/except urllib.error.HTTPError` block. Define a typed
  `EmbeddingServiceError(status_code, dream_id)` exception. Log the HTTP
  status code and dream_id on failure before raising. Add unit tests for
  429 and 500 HTTP responses.

Acceptance-Criteria:
  - id: AC-1
    description: "A mocked 429 response from the OpenAI embeddings endpoint causes `_send_embedding_request()` to raise `EmbeddingServiceError` with `status_code=429` and the correct `dream_id`. Verified by tests/unit/test_rag_ingestion.py::test_embed_raises_on_429."
    test: "tests/unit/test_rag_ingestion.py::test_embed_raises_on_429"
  - id: AC-2
    description: "A mocked 500 response causes `_send_embedding_request()` to raise `EmbeddingServiceError` with `status_code=500`. Verified by tests/unit/test_rag_ingestion.py::test_embed_raises_on_500."
    test: "tests/unit/test_rag_ingestion.py::test_embed_raises_on_500"
  - id: AC-3
    description: "On HTTP error, the error is logged with `dream_id` and `status_code` before the exception is raised. Verified by tests/unit/test_rag_ingestion.py::test_embed_logs_dream_id_on_error."
    test: "tests/unit/test_rag_ingestion.py::test_embed_logs_dream_id_on_error"

Files:
  - app/retrieval/ingestion.py
  - tests/unit/test_rag_ingestion.py

Notes: |
  `EmbeddingServiceError` may be defined inline in `app/retrieval/ingestion.py`
  or in a shared `app/shared/exceptions.py` module if one exists.
  Do NOT allow raw `urllib.error.HTTPError` to propagate beyond the
  `_send_embedding_request()` boundary.

---

## FIX-C3-2: Replace `_token_count()` Word-Split with tiktoken-Based Token Count

Owner:      codex
Phase:      3
Type:       fix
Depends-On: T10
Finding:    CODE-20 [P1]

Objective: |
  Replace the whitespace-split word count in `_token_count()` at
  `app/retrieval/ingestion.py:238–239` with a tiktoken `cl100k_base`
  encoder call. Add `tiktoken` to `requirements.txt`. Update
  `test_chunking_boundary` to use input text with a known real token count
  rather than an approximate word count.

Acceptance-Criteria:
  - id: AC-1
    description: "`_token_count(text)` returns the same count as `len(tiktoken.get_encoding('cl100k_base').encode(text))` for a 100-word English prose sample. Verified by tests/unit/test_rag_ingestion.py::test_token_count_uses_tiktoken."
    test: "tests/unit/test_rag_ingestion.py::test_token_count_uses_tiktoken"
  - id: AC-2
    description: "All chunks produced by `_chunk_text()` on a 600-real-token prose input have `_token_count(chunk) <= 512`. Verified by tests/unit/test_rag_ingestion.py::test_chunks_do_not_exceed_512_real_tokens."
    test: "tests/unit/test_rag_ingestion.py::test_chunks_do_not_exceed_512_real_tokens"
  - id: AC-3
    description: "`requirements.txt` contains `tiktoken`. Verified by tests/unit/test_rag_ingestion.py::test_tiktoken_in_requirements."
    test: "tests/unit/test_rag_ingestion.py::test_tiktoken_in_requirements"

Files:
  - app/retrieval/ingestion.py
  - requirements.txt
  - tests/unit/test_rag_ingestion.py

Notes: |
  Use `tiktoken.get_encoding("cl100k_base")` — same encoder family as
  `text-embedding-3-small`. Cache the encoder instance at module level
  to avoid repeated initialisation overhead.
  The 50-token overlap constant (`CHUNK_OVERLAP_TOKENS`) must also use
  real token units after this fix — verify it is already applied correctly
  in the chunking loop.

---

## Phase 2: Analysis Pipeline

Goal: The system can segment a Google Doc into dream entries, maintain a theme taxonomy, extract per-dream themes using the LLM, and ground each theme to supporting text fragments with a salience score. All outputs are in `draft` status pending user confirmation.

Phase gate: All analysis pipeline tests pass; theme extraction produces valid structured output; fragment grounding links to text spans that exist in the source entry; annotation versions written on every mutation.

---

## T06: Dream Segmentation Service

Owner:      codex
Phase:      2
Type:       none
Depends-On: T04, T05

Objective: |
  Implement the segmentation service that converts a list of raw document paragraphs
  into individual DreamEntry records. Deterministic boundary detection handles standard
  date-header formats; LLM call resolves ambiguous cases.

Acceptance-Criteria:
  - id: AC-1
    description: "A document with 5 entries separated by `YYYY-MM-DD` date headers is segmented into exactly 5 DreamEntry records with correct dates. Verified by tests/unit/test_segmentation.py::test_standard_date_header_segmentation."
    test: "tests/unit/test_segmentation.py::test_standard_date_header_segmentation"
  - id: AC-2
    description: "A document with no recognizable date headers returns 1 DreamEntry record with `date=None` and `segmentation_confidence='low'`. Verified by tests/unit/test_segmentation.py::test_no_date_header_fallback."
    test: "tests/unit/test_segmentation.py::test_no_date_header_fallback"
  - id: AC-3
    description: "Content hash deduplication: calling `segment_and_store()` twice on the same paragraphs inserts 0 new records on the second call. Verified by tests/integration/test_segmentation.py::test_deduplication_by_content_hash."
    test: "tests/integration/test_segmentation.py::test_deduplication_by_content_hash"
  - id: AC-4
    description: "Dream entry `raw_text` contains no OAuth credentials, API keys, or content from env vars. Verified by tests/unit/test_segmentation.py::test_raw_text_contains_no_secrets."
    test: "tests/unit/test_segmentation.py::test_raw_text_contains_no_secrets"

Files:
  - app/services/segmentation.py
  - tests/unit/test_segmentation.py
  - tests/integration/test_segmentation.py

Notes: |
  Date header regex: match `YYYY-MM-DD`, `DD.MM.YYYY`, `Month DD, YYYY` formats.
  LLM fallback (via app/llm/client.py) is called only when the deterministic pass finds
  0 boundaries in a document with > 1000 words. This avoids unnecessary LLM cost.

---

## T07: Theme Taxonomy System

Owner:      codex
Phase:      2
Type:       none
Depends-On: T04

Objective: |
  Implement the theme category CRUD service with the approval state machine.
  Seed a set of predefined starter categories. All category mutations write
  an AnnotationVersion record before the change is applied.

Acceptance-Criteria:
  - id: AC-1
    description: "`TaxonomyService.create_category(name, description)` inserts a record with `status='suggested'` and returns the new category ID. Verified by tests/integration/test_taxonomy.py::test_create_category_defaults_to_suggested."
    test: "tests/integration/test_taxonomy.py::test_create_category_defaults_to_suggested"
  - id: AC-2
    description: "`TaxonomyService.approve_category(id)` transitions `suggested` → `active` and writes an AnnotationVersion snapshot. Verified by tests/integration/test_taxonomy.py::test_approve_category_writes_annotation_version."
    test: "tests/integration/test_taxonomy.py::test_approve_category_writes_annotation_version"
  - id: AC-3
    description: "`TaxonomyService.deprecate_category(id)` sets `status='deprecated'` without deleting the row; associated DreamTheme records retain the category_id with a `deprecated=True` flag. Verified by tests/integration/test_taxonomy.py::test_deprecate_category_soft_delete."
    test: "tests/integration/test_taxonomy.py::test_deprecate_category_soft_delete"
  - id: AC-4
    description: "After DB migration, at least 5 predefined starter categories exist with `status='active'`. Verified by tests/integration/test_taxonomy.py::test_seed_categories_present."
    test: "tests/integration/test_taxonomy.py::test_seed_categories_present"

Files:
  - app/services/taxonomy.py
  - alembic/versions/002_seed_categories.py
  - tests/integration/test_taxonomy.py

Notes: |
  Starter categories (seed data): "separation", "mother_figure", "shadow",
  "inner_child", "transformation", "water", "flying", "pursuit", "house_rooms", "death_rebirth".
  These are active from the start. Additional categories emerge as suggestions from the LLM.

---

## T08: Per-Dream Theme Extraction (LLM)

Owner:      codex
Phase:      2
Type:       none
Depends-On: T06, T07

Objective: |
  Implement the LLM-based theme extraction service. For a given DreamEntry, produce
  a structured list of (category_id, salience, match_type, justification) tuples using
  claude-haiku-4-5 with structured output. Save results as draft DreamTheme records.

Acceptance-Criteria:
  - id: AC-1
    description: "`ThemeExtractor.extract(dream_entry, categories)` returns a list of ThemeAssignment objects each with: `category_id` (from the provided list), `salience` (float 0.0–1.0), `match_type` ('literal'/'semantic'/'symbolic'), `justification` (string). Verified by tests/unit/test_theme_extractor.py::test_extract_returns_valid_structure."
    test: "tests/unit/test_theme_extractor.py::test_extract_returns_valid_structure"
  - id: AC-2
    description: "All category_ids in the returned assignments reference categories that exist in the provided `categories` list (no hallucinated IDs). Verified by tests/unit/test_theme_extractor.py::test_no_hallucinated_category_ids."
    test: "tests/unit/test_theme_extractor.py::test_no_hallucinated_category_ids"
  - id: AC-3
    description: "`AnalysisService.analyse_dream(dream_id)` stores extracted themes as DreamTheme records with `status='draft'` in the database. Verified by tests/integration/test_analysis.py::test_analysis_saves_draft_themes."
    test: "tests/integration/test_analysis.py::test_analysis_saves_draft_themes"
  - id: AC-4
    description: "Running `analyse_dream()` on the same dream_id twice produces ≥80% overlap in the top-3 returned category_ids (tested with a fixed LLM test double). Verified by tests/unit/test_theme_extractor.py::test_extraction_consistency."
    test: "tests/unit/test_theme_extractor.py::test_extraction_consistency"

Files:
  - app/llm/client.py
  - app/llm/theme_extractor.py
  - app/services/analysis.py
  - tests/unit/test_theme_extractor.py
  - tests/integration/test_analysis.py

Notes: |
  Use a test double (mock LLM client) for unit tests. Integration tests may call the real
  API if ANTHROPIC_API_KEY is present; otherwise skip.
  The structured output schema: `{"themes": [{"category_id": "...", "salience": 0.7,
  "match_type": "symbolic", "justification": "..."}]}`.
  Validate the JSON schema on the LLM response before saving. Malformed response → retry once,
  then raise `ThemeExtractionError`.

---

## T09: Salience Ranking and Fragment Grounding

Owner:      codex
Phase:      2
Type:       none
Depends-On: T08

Objective: |
  For each extracted theme, identify the specific text spans in the dream entry that
  most strongly support the theme assignment. Use claude-sonnet-4-6 to rank themes by
  salience and locate supporting fragments with character offsets. Save fragment data
  in the DreamTheme.fragments JSONB field.

Acceptance-Criteria:
  - id: AC-1
    description: "`Grounder.ground(dream_entry, theme_assignments)` returns a list of GroundedTheme objects each with: `category_id`, `salience` (re-ranked float), `fragments` (list of `{text, start_offset, end_offset, match_type}`). Verified by tests/unit/test_grounder.py::test_ground_returns_grounded_themes."
    test: "tests/unit/test_grounder.py::test_ground_returns_grounded_themes"
  - id: AC-2
    description: "Every fragment's `text` is a substring of the original `dream_entry.raw_text` at the stated `start_offset`:`end_offset`. Verified by tests/unit/test_grounder.py::test_fragment_text_matches_source_offsets."
    test: "tests/unit/test_grounder.py::test_fragment_text_matches_source_offsets"
  - id: AC-3
    description: "DreamTheme records in the database have a non-null `fragments` JSON array after grounding completes. Verified by tests/integration/test_analysis.py::test_grounded_themes_have_fragments."
    test: "tests/integration/test_analysis.py::test_grounded_themes_have_fragments"
  - id: AC-4
    description: "An AnnotationVersion snapshot is written before updating any existing DreamTheme record during re-grounding. Verified by tests/integration/test_analysis.py::test_regrounding_writes_annotation_version."
    test: "tests/integration/test_analysis.py::test_regrounding_writes_annotation_version"

Files:
  - app/llm/grounder.py
  - tests/unit/test_grounder.py

Notes: |
  Fragment offsets are character-level (not token-level) relative to `dream_entry.raw_text`.
  If the LLM returns a fragment that cannot be verified as a substring of the source text,
  store it with `verified=False` rather than rejecting the entire response.
  Grounding is called after extraction in `AnalysisService.analyse_dream()`.

---

## Fix Tasks — Cycle 4 (resolve before T12 DONE gate)

---

## FIX-C4-1: Add HTTP Error Handling to `query.py` `_send_embedding_request()`

Owner:      codex
Phase:      3
Type:       fix
Depends-On: T11
Finding:    CODE-26 [P1]

Objective: |
  Wrap `urllib.request.urlopen()` in `_send_embedding_request()` in
  `app/retrieval/query.py` with a `try/except urllib.error.HTTPError` block.
  Define a typed `QueryEmbeddingError(status_code, query_length)` exception.
  Log `status_code` and `query_length` (NOT query text — PII policy) on
  failure before raising. Add unit tests for 429 and 500 HTTP responses.

Acceptance-Criteria:
  - id: AC-1
    description: "A mocked 429 response from the OpenAI embeddings endpoint causes `_send_embedding_request()` in `query.py` to raise `QueryEmbeddingError` with `status_code=429`. Verified by tests/unit/test_rag_query.py::test_query_embed_raises_on_429."
    test: "tests/unit/test_rag_query.py::test_query_embed_raises_on_429"
  - id: AC-2
    description: "A mocked 500 response causes `_send_embedding_request()` to raise `QueryEmbeddingError` with `status_code=500`. Verified by tests/unit/test_rag_query.py::test_query_embed_raises_on_500."
    test: "tests/unit/test_rag_query.py::test_query_embed_raises_on_500"
  - id: AC-3
    description: "On HTTP error, the error is logged with `status_code` and `query_length` (not query text) before the exception is raised. Verified by tests/unit/test_rag_query.py::test_query_embed_logs_on_error."
    test: "tests/unit/test_rag_query.py::test_query_embed_logs_on_error"

Files:
  - app/retrieval/query.py
  - tests/unit/test_rag_query.py

Notes: |
  `QueryEmbeddingError` may be defined inline in `app/retrieval/query.py`.
  Do NOT log query text — only `status_code` and `query_length` (integer).
  Do NOT allow raw `urllib.error.HTTPError` to propagate beyond the
  `_send_embedding_request()` boundary.
  This fix mirrors FIX-C3-1 (CODE-19) applied to `ingestion.py`.

---

## Phase 3: Retrieval (RAG)

Goal: Dream entries and their annotations are embedded, indexed in pgvector, and retrievable via hybrid semantic + lexical search. The `insufficient_evidence` path is tested and mandatory. A retrieval evaluation baseline is established.

Phase gate: RAG ingestion pipeline indexes a seeded corpus of 20 entries; hybrid query returns ranked results; `insufficient_evidence` returned for zero-match queries; retrieval_eval.md baseline recorded.

---

## T10: RAG Ingestion Pipeline — Chunk, Embed, Index

Owner:      codex
Phase:      3
Type:       rag:ingestion
Depends-On: T04, T05

Objective: |
  Implement the RAG ingestion pipeline: chunk each DreamEntry into one or more text
  segments, generate embeddings via the OpenAI embeddings API, and upsert into the
  dream_chunks table with pgvector storage. The pipeline is idempotent: re-indexing
  the same entry updates existing chunks rather than creating duplicates.

Acceptance-Criteria:
  - id: AC-1
    description: "`RagIngestionService.index_dream(dream_id)` inserts at least one DreamChunk row with a non-null `embedding` (vector of dimension 1536) for a DreamEntry with 100 words. Verified by tests/integration/test_rag_ingestion.py::test_index_dream_creates_chunk_with_embedding."
    test: "tests/integration/test_rag_ingestion.py::test_index_dream_creates_chunk_with_embedding"
  - id: AC-2
    description: "Calling `index_dream(dream_id)` twice for the same entry results in the same number of rows (no duplicate chunks). Verified by tests/integration/test_rag_ingestion.py::test_index_dream_idempotent."
    test: "tests/integration/test_rag_ingestion.py::test_index_dream_idempotent"
  - id: AC-3
    description: "A DreamEntry with 600 tokens is split into 2 chunks. A DreamEntry with 300 tokens produces 1 chunk. Verified by tests/unit/test_rag_ingestion.py::test_chunking_boundary."
    test: "tests/unit/test_rag_ingestion.py::test_chunking_boundary"
  - id: AC-4
    description: "The ingestion pipeline code (`app/retrieval/ingestion.py`) imports no symbols from `app/retrieval/query.py` (ingestion and query-time are separate modules). Verified by tests/unit/test_rag_ingestion.py::test_ingestion_does_not_import_query_module."
    test: "tests/unit/test_rag_ingestion.py::test_ingestion_does_not_import_query_module"

Files:
  - app/retrieval/ingestion.py
  - tests/unit/test_rag_ingestion.py
  - tests/integration/test_rag_ingestion.py
  - docs/retrieval_eval.md

Context-Refs:
  - docs/ARCHITECTURE.md#rag-architecture
  - docs/IMPLEMENTATION_CONTRACT.md#profile-rules-rag

Notes: |
  Embedding API calls are made in batches of up to 100 chunks to respect rate limits.
  Store `chunk_index` (0-based) to reconstruct the full entry order.
  The index schema version (v1) must be stored in a config constant, not hardcoded in the pipeline.
  Initialize docs/retrieval_eval.md with the template from templates/RETRIEVAL_EVAL.md.

Execution-Mode: heavy
Evidence:
  - docs/retrieval_eval.md updated with ingestion stage metrics
  - ingestion/query module separation verified in tests
Verifier-Focus: |
  Confirm ingestion and query code are in separate modules with no cross-imports.
  Confirm the retrieval_eval.md is initialized with schema version v1 recorded.

---

## T11: RAG Query Pipeline — Hybrid Retrieval and Evidence Assembly

Owner:      codex
Phase:      3
Type:       rag:query
Depends-On: T10

Objective: |
  Implement the query-time retrieval pipeline: expand the query for metaphor-aware
  matching, execute hybrid search (pgvector cosine + PostgreSQL FTS with RRF fusion),
  filter by relevance threshold, assemble evidence blocks, and return
  `insufficient_evidence` when no chunks pass the threshold.

Acceptance-Criteria:
  - id: AC-1
    description: "`RagQueryService.retrieve(query)` returns a list of EvidenceBlock objects (each with: dream_id, date, chunk_text, relevance_score, matched_fragments) when the corpus contains at least one relevant entry. Verified by tests/integration/test_rag_query.py::test_retrieve_returns_evidence_blocks."
    test: "tests/integration/test_rag_query.py::test_retrieve_returns_evidence_blocks"
  - id: AC-2
    description: "`RagQueryService.retrieve(query)` returns `InsufficientEvidence` sentinel (not an exception) when the query matches 0 chunks above the relevance threshold. Verified by tests/integration/test_rag_query.py::test_retrieve_returns_insufficient_evidence_for_zero_match."
    test: "tests/integration/test_rag_query.py::test_retrieve_returns_insufficient_evidence_for_zero_match"
  - id: AC-3
    description: "Hybrid search fuses pgvector cosine and FTS scores; a query that is a keyword match but not a semantic match returns results (not `insufficient_evidence`). Verified by tests/integration/test_rag_query.py::test_hybrid_search_returns_keyword_only_match."
    test: "tests/integration/test_rag_query.py::test_hybrid_search_returns_keyword_only_match"
  - id: AC-4
    description: "The query pipeline code (`app/retrieval/query.py`) imports no symbols from `app/retrieval/ingestion.py`. Verified by tests/unit/test_rag_query.py::test_query_does_not_import_ingestion_module."
    test: "tests/unit/test_rag_query.py::test_query_does_not_import_ingestion_module"
  - id: AC-5
    description: "`GET /health` response includes `index_last_updated` ISO8601 timestamp and returns HTTP 503 if the index age exceeds `MAX_INDEX_AGE_HOURS`. Verified by tests/integration/test_rag_query.py::test_health_degrades_on_stale_index."
    test: "tests/integration/test_rag_query.py::test_health_degrades_on_stale_index"

Files:
  - app/retrieval/query.py
  - tests/unit/test_rag_query.py
  - tests/integration/test_rag_query.py

Context-Refs:
  - docs/ARCHITECTURE.md#rag-architecture
  - docs/IMPLEMENTATION_CONTRACT.md#insufficient_evidence-path

Notes: |
  RRF fusion formula: score = 1/(k + rank_cosine) + 1/(k + rank_fts), k=60 by default.
  `InsufficientEvidence` is a dataclass (not an exception) so callers handle it without try/except.
  The health endpoint update (stale index → 503) is in `app/api/health.py`.

---

## T12: Retrieval Evaluation Baseline

Owner:      codex
Phase:      3
Type:       rag:query
Depends-On: T11

Objective: |
  Establish the retrieval evaluation baseline by defining a 10-query evaluation dataset,
  implementing an evaluation script, running it against the seeded corpus, and recording
  results in docs/retrieval_eval.md. The baseline must be recorded before Phase 4 begins.

Acceptance-Criteria:
  - id: AC-1
    description: "`docs/retrieval_eval.md §Evaluation Dataset` contains at least 10 queries covering all four query types: simple, multi-doc, multi-hop, no-answer. Verified by tests/unit/test_retrieval_eval.py::test_eval_dataset_covers_all_query_types."
    test: "tests/unit/test_retrieval_eval.py::test_eval_dataset_covers_all_query_types"
  - id: AC-2
    description: "`scripts/eval.py` runs against a seeded 20-entry corpus and writes hit@3, MRR, and no-answer accuracy to `docs/retrieval_eval.md §Baseline Metrics`. Verified by tests/integration/test_retrieval_eval.py::test_eval_script_writes_baseline_metrics."
    test: "tests/integration/test_retrieval_eval.py::test_eval_script_writes_baseline_metrics"
  - id: AC-3
    description: "`docs/retrieval_eval.md §Evaluation History` contains at least 1 row with non-null: Date, Task, Corpus Version, Eval Source, hit@3, MRR. Verified by tests/unit/test_retrieval_eval.py::test_eval_history_has_valid_first_entry."
    test: "tests/unit/test_retrieval_eval.py::test_eval_history_has_valid_first_entry"
  - id: AC-4
    description: "No-answer queries (those with no relevant document in the seeded corpus) all return `InsufficientEvidence` (no-answer accuracy = 1.0 on the seeded dataset). Verified by tests/integration/test_retrieval_eval.py::test_no_answer_queries_return_insufficient_evidence."
    test: "tests/integration/test_retrieval_eval.py::test_no_answer_queries_return_insufficient_evidence"

Files:
  - scripts/eval.py
  - tests/unit/test_retrieval_eval.py
  - tests/integration/test_retrieval_eval.py
  - docs/retrieval_eval.md

Context-Refs:
  - docs/ARCHITECTURE.md#index-strategy
  - docs/IMPLEMENTATION_CONTRACT.md#retrieval-evaluation-gate

Notes: |
  The seeded corpus (20 synthetic dream entries) lives in `tests/fixtures/seed_dreams.json`.
  Eval source for the history row: "scripts/eval.py against §Evaluation Dataset (10 queries), run 2026-04-10"
  hit@3 target: ≥ 0.70 on the seeded corpus (baseline, not production target).
  This task closes the RAG Phase 3 gate.

---

## Fix Tasks — Cycle 5 (resolve before T13 DONE gate)

---

## FIX-C5-1: Remove Dead `except HTTPError` Guard in `embed()` — `query.py` and `ingestion.py`

Owner:      codex
Phase:      4
Type:       fix
Depends-On: T12
Finding:    CODE-33 [P1]

Objective: |
  Remove the unreachable `except urllib_error.HTTPError` guard from
  `OpenAIEmbeddingClient.embed()` in both `app/retrieval/query.py` and
  `app/retrieval/ingestion.py`. The sync helper `_send_embedding_request()`
  already converts `HTTPError` into a typed exception; the async caller's
  guard is dead code that creates false confidence in two-level error handling.

Acceptance-Criteria:
  - id: AC-1
    description: "`OpenAIEmbeddingClient.embed()` in `query.py` contains no `except urllib_error.HTTPError` block. Verified by grep and by tests/unit/test_rag_query.py::test_query_embed_raises_on_429 and test_query_embed_raises_on_500 still passing."
    test: "tests/unit/test_rag_query.py::test_query_embed_raises_on_429"
  - id: AC-2
    description: "`OpenAIEmbeddingClient.embed()` in `ingestion.py` contains no `except urllib_error.HTTPError` block. Verified by grep and by tests/unit/test_rag_ingestion.py::test_embed_raises_on_429 and test_embed_raises_on_500 still passing."
    test: "tests/unit/test_rag_ingestion.py::test_embed_raises_on_429"
  - id: AC-3
    description: "All pre-existing embed HTTP error tests (429 and 500 in both files) continue to pass after the guard removal, confirming the sync helper's typed error propagates correctly."
    test: "tests/unit/test_rag_ingestion.py::test_embed_raises_on_500"

Files:
  - app/retrieval/query.py
  - app/retrieval/ingestion.py

Notes: |
  This is a deletion-only fix. Do NOT modify `_send_embedding_request()` or
  its `try/except urllib.error.HTTPError` block — that is the correct,
  active handler. Only remove the dead guard in the async `embed()` caller.
  Verify with: grep -n "except urllib_error.HTTPError" app/retrieval/query.py
  and app/retrieval/ingestion.py — both must return 0 matches in embed().

---

## FIX-C5-2: Close Aging P2 Carry-Forwards — CODE-2, CODE-5/35, CODE-11/36, CODE-12/37

Owner:      codex
Phase:      4
Type:       fix
Depends-On: T12
Findings:   CODE-2 [P2], CODE-35 [P2] (carry-forward CODE-5), CODE-36 [P2] (carry-forward CODE-11), CODE-37 [P2] (carry-forward CODE-12)

Objective: |
  Resolve four aging P2 findings that have breached the 3–4 cycle age cap.
  All four are isolated, low-risk changes that can be addressed in a single commit.
  1. CODE-2: Add parametrised unit test asserting non-auth `HttpError` (e.g. 500)
     in `GDocsClient.fetch_document()` is re-raised as-is (not wrapped as `GDocsAuthError`).
  2. CODE-35 (CODE-5): Add `fragments IS NOT NULL` column assertion and a parametrised
     positive-domain INSERT test for the CHECK constraint (draft/confirmed/rejected)
     to `tests/integration/test_migrations.py`.
  3. CODE-36 (CODE-11): Remove all three `@pytest.mark.skipif(not os.getenv("ANTHROPIC_API_KEY"), ...)`
     decorators from `tests/integration/test_analysis.py:167–170, 213–216, 250–253`.
  4. CODE-37 (CODE-12): Make `StubGrounder` set `verified=False` for the second fragment;
     add assertion `fragments[1]["verified"] is False` in the integration test.

Acceptance-Criteria:
  - id: AC-1
    description: "A parametrised test in `tests/unit/test_gdocs_client.py` asserts that a non-auth HTTPError (status 500) raised by `urlopen` propagates from `GDocsClient.fetch_document()` as-is, not as `GDocsAuthError`. Verified by tests/unit/test_gdocs_client.py::test_non_auth_http_error_propagates."
    test: "tests/unit/test_gdocs_client.py::test_non_auth_http_error_propagates"
  - id: AC-2
    description: "`tests/integration/test_migrations.py` asserts `is_nullable == 'NO'` for the `fragments` column, and a parametrised INSERT test verifies all three valid CHECK domain values (draft/confirmed/rejected) succeed without IntegrityError. Verified by tests/integration/test_migrations.py::test_fragments_not_null and test_dream_themes_status_check_domain."
    test: "tests/integration/test_migrations.py::test_fragments_not_null"
  - id: AC-3
    description: "All three previously-skipped analysis integration tests run without `@pytest.mark.skipif` guards and pass using stub doubles. Verified by tests/integration/test_analysis.py (three previously-guarded tests now execute unconditionally)."
    test: "tests/integration/test_analysis.py"
  - id: AC-4
    description: "`StubGrounder` sets `verified=False` for the second fragment; integration test asserts `fragments[1]['verified'] is False`. Verified by tests/integration/test_analysis.py::test_grounded_themes_have_fragments."
    test: "tests/integration/test_analysis.py::test_grounded_themes_have_fragments"

Files:
  - tests/unit/test_gdocs_client.py
  - tests/integration/test_migrations.py
  - tests/integration/test_analysis.py

Notes: |
  These are all test-only changes with the exception of the one-line StubGrounder
  edit (test helper, not production code). No production .py files require modification.
  All four changes are isolated; a single commit is acceptable.
  After this fix, CODE-2, CODE-5, CODE-11, and CODE-12 are all closed.

---

## Phase 4: API Layer and Workers

Goal: All archive operations are accessible via a documented HTTP API. Background workers handle async ingestion and indexing. The health endpoint reflects index freshness.

Phase gate: All API endpoints return correct status codes for happy paths and error cases; background workers enqueue and process jobs; full flow from sync trigger to searchable archive works end-to-end.

---

## T13: Health Endpoint and Observability

Owner:      codex
Phase:      4
Type:       none
Depends-On: T03, T10

Objective: |
  Finalize the health endpoint with index freshness reporting. Ensure all external calls
  (DB, Redis, Google Docs API, Anthropic API, OpenAI API) are wrapped in OpenTelemetry
  spans using the shared tracing module. Add structlog JSON logging with trace_id injection.

Acceptance-Criteria:
  - id: AC-1
    description: "`GET /health` returns `{\"status\": \"ok\", \"index_last_updated\": \"<ISO8601>\"}` (HTTP 200) when the index was updated within `MAX_INDEX_AGE_HOURS`. Verified by tests/integration/test_health.py::test_health_returns_ok_with_fresh_index."
    test: "tests/integration/test_health.py::test_health_returns_ok_with_fresh_index"
  - id: AC-2
    description: "`GET /health` returns HTTP 503 when `index_last_updated` is older than `MAX_INDEX_AGE_HOURS`. Verified by tests/integration/test_health.py::test_health_returns_503_on_stale_index."
    test: "tests/integration/test_health.py::test_health_returns_503_on_stale_index"
  - id: AC-3
    description: "Every SQLAlchemy DB query is executed within an OpenTelemetry span created via `app/shared/tracing.py::get_tracer()`. No inline noop span implementations exist in service or model files. Verified by tests/unit/test_tracing.py::test_no_inline_tracer_instances."
    test: "tests/unit/test_tracing.py::test_no_inline_tracer_instances"
  - id: AC-4
    description: "Log output from a request contains `trace_id`, `span_id`, `env`, and `service` fields; contains no dream `raw_text`. Verified by tests/unit/test_tracing.py::test_log_fields_present_and_no_pii."
    test: "tests/unit/test_tracing.py::test_log_fields_present_and_no_pii"

Files:
  - app/api/health.py
  - app/shared/tracing.py
  - tests/unit/test_tracing.py

Notes: |
  structlog configured in `app/main.py` startup with JSON renderer.
  trace_id injected into log context via OpenTelemetry context propagation.

---

## T14: Ingestion and Sync API Endpoints

Owner:      codex
Phase:      4
Type:       none
Depends-On: T06, T13

Objective: |
  Implement the sync trigger API and dream listing endpoints. `POST /sync` enqueues an
  ARQ job and returns a job ID. `GET /sync/{job_id}` returns job status. `GET /dreams`
  returns paginated dream entries. `GET /dreams/{id}` returns a single entry with metadata.

Acceptance-Criteria:
  - id: AC-1
    description: "`POST /sync` returns HTTP 202 with `{\"job_id\": \"<uuid>\", \"status\": \"queued\"}` when the request is authenticated. Verified by tests/integration/test_dreams_api.py::test_post_sync_returns_202."
    test: "tests/integration/test_dreams_api.py::test_post_sync_returns_202"
  - id: AC-2
    description: "`POST /sync` returns HTTP 401 when called without authentication. Verified by tests/integration/test_dreams_api.py::test_post_sync_requires_auth."
    test: "tests/integration/test_dreams_api.py::test_post_sync_requires_auth"
  - id: AC-3
    description: "`GET /dreams` returns HTTP 200 with `{\"items\": [...], \"total\": N, \"page\": 1}` and supports `?page=` and `?page_size=` query params. Verified by tests/integration/test_dreams_api.py::test_get_dreams_paginated."
    test: "tests/integration/test_dreams_api.py::test_get_dreams_paginated"
  - id: AC-4
    description: "`GET /dreams/{id}` returns HTTP 404 for a non-existent ID; HTTP 200 with the full entry record for a valid ID. Verified by tests/integration/test_dreams_api.py::test_get_dream_by_id."
    test: "tests/integration/test_dreams_api.py::test_get_dream_by_id"

Files:
  - app/api/dreams.py
  - tests/integration/test_dreams_api.py

Notes: |
  Authentication middleware is applied globally in `app/main.py`.
  For v1, auth is a simple API key check (X-API-Key header) stored hashed in the DB.
  Pagination default: page_size=20, max page_size=100.

---

## T15: Dream Browsing and Theme Search API

Owner:      codex
Phase:      4
Type:       rag:query
Depends-On: T11, T14

Objective: |
  Implement the search API endpoints and the per-dream theme retrieval endpoint.
  `GET /search` executes hybrid retrieval and returns matched entries with evidence.
  `GET /dreams/{id}/themes` returns all theme assignments for a dream.

Acceptance-Criteria:
  - id: AC-1
    description: "`GET /search?q=flying` returns HTTP 200 with up to 5 dream entries ranked by relevance, each including `dream_id`, `date`, `matched_fragments`, `relevance_score`, and `theme_matches`. Verified by tests/integration/test_search_api.py::test_search_returns_ranked_results."
    test: "tests/integration/test_search_api.py::test_search_returns_ranked_results"
  - id: AC-2
    description: "`GET /search?q=<query_with_no_matches>` returns HTTP 200 with `{\"result\": \"insufficient_evidence\", \"query\": \"...\", \"expanded_terms\": [...]}`. Verified by tests/integration/test_search_api.py::test_search_returns_insufficient_evidence."
    test: "tests/integration/test_search_api.py::test_search_returns_insufficient_evidence"
  - id: AC-3
    description: "`GET /search?q=separation&theme_ids=<id1>` filters results to entries that have a confirmed DreamTheme with category_id=<id1>. Verified by tests/integration/test_search_api.py::test_search_with_theme_filter."
    test: "tests/integration/test_search_api.py::test_search_with_theme_filter"
  - id: AC-4
    description: "`GET /dreams/{id}/themes` returns themes sorted by `salience` descending; each theme includes `category_id`, `salience`, `match_type`, `status`, `fragments`. Verified by tests/integration/test_search_api.py::test_get_dream_themes_sorted_by_salience."
    test: "tests/integration/test_search_api.py::test_get_dream_themes_sorted_by_salience"

Files:
  - app/api/search.py
  - tests/integration/test_search_api.py

Context-Refs:
  - docs/retrieval_eval.md

Notes: |
  Search endpoint requires authentication.
  `expanded_terms` is always included in the response, even when insufficient_evidence is returned.

---

## T16: User Curation API — Theme Confirmation and Taxonomy Management

Owner:      codex
Phase:      4
Type:       none
Depends-On: T07, T09, T14

Objective: |
  Implement the curation API: confirm/reject draft themes, create manual themes,
  manage theme categories (create, approve, deprecate), and the bulk confirmation
  approval flow. All mutations write AnnotationVersion records.

Acceptance-Criteria:
  - id: AC-1
    description: "`PATCH /dreams/{id}/themes/{theme_id}/confirm` transitions `status` from `draft` to `confirmed`; returns HTTP 200. Verified by tests/integration/test_curation_api.py::test_confirm_theme_transitions_status."
    test: "tests/integration/test_curation_api.py::test_confirm_theme_transitions_status"
  - id: AC-2
    description: "`PATCH /dreams/{id}/themes/{theme_id}/reject` transitions `status` from `draft` to `rejected`; returns HTTP 200. Rejected themes are excluded from `GET /dreams/{id}/themes` responses (not returned by default). Verified by tests/integration/test_curation_api.py::test_reject_theme_excluded_from_listing."
    test: "tests/integration/test_curation_api.py::test_reject_theme_excluded_from_listing"
  - id: AC-3
    description: "`POST /curate/bulk-confirm` with a list of >1 dream_ids returns `{\"requires_approval\": true, \"token\": \"...\"}` and does NOT commit any status changes until `POST /curate/bulk-confirm/{token}/approve` is called. Verified by tests/integration/test_curation_api.py::test_bulk_confirm_requires_approval_step."
    test: "tests/integration/test_curation_api.py::test_bulk_confirm_requires_approval_step"
  - id: AC-4
    description: "`PATCH /themes/categories/{id}/approve` returns HTTP 403 when called without authentication; HTTP 200 and sets `status='active'` when authenticated. Verified by tests/integration/test_curation_api.py::test_approve_category_requires_auth."
    test: "tests/integration/test_curation_api.py::test_approve_category_requires_auth"
  - id: AC-5
    description: "Every successful theme confirmation or category mutation creates an AnnotationVersion row before the mutation is committed. Verified by tests/integration/test_curation_api.py::test_mutation_writes_annotation_version."
    test: "tests/integration/test_curation_api.py::test_mutation_writes_annotation_version"

Files:
  - app/api/themes.py
  - tests/integration/test_curation_api.py

Notes: |
  Bulk-confirm token is a UUID stored in Redis with a 10-minute TTL.
  Expired tokens return HTTP 410 Gone.
  Bulk confirmation of exactly 1 dream does NOT require the approval step.

---

## T17: Background Worker Setup with Idempotency

Owner:      codex
Phase:      4
Type:       none
Depends-On: T05, T10, T14

Objective: |
  Implement ARQ background workers for ingestion and indexing jobs. Workers must be
  idempotent: re-queuing the same job produces no duplicate records. Workers update
  job status in Redis so `GET /sync/{job_id}` reflects real-time progress.

Acceptance-Criteria:
  - id: AC-1
    description: "Enqueuing `ingest_document` twice with the same `doc_id` and identical content results in 0 new DreamEntry rows on the second run. Verified by tests/integration/test_workers.py::test_ingest_job_idempotent."
    test: "tests/integration/test_workers.py::test_ingest_job_idempotent"
  - id: AC-2
    description: "After `ingest_document` completes, `GET /sync/{job_id}` returns `{\"status\": \"done\", \"new_entries\": N}`. Verified by tests/integration/test_workers.py::test_sync_job_status_done_after_completion."
    test: "tests/integration/test_workers.py::test_sync_job_status_done_after_completion"
  - id: AC-3
    description: "If the Google Docs API call in the worker raises `GDocsAuthError`, the job status becomes `failed` and no partial records are inserted. Verified by tests/integration/test_workers.py::test_ingest_job_fails_cleanly_on_auth_error."
    test: "tests/integration/test_workers.py::test_ingest_job_fails_cleanly_on_auth_error"
  - id: AC-4
    description: "`index_dream` worker re-indexes a dream entry without creating duplicate chunks (upsert by dream_id + chunk_index). Verified by tests/integration/test_workers.py::test_index_worker_idempotent."
    test: "tests/integration/test_workers.py::test_index_worker_idempotent"

Files:
  - app/workers/ingest.py
  - app/workers/index.py
  - tests/integration/test_workers.py

Notes: |
  ARQ worker settings configured in `app/shared/config.py`.
  Workers use the same async SQLAlchemy session factory as the API.

---

## Phase 5: Archive Intelligence and Hardening

Goal: Archive-level pattern analysis is available via API. Annotation versioning and rollback are operational. End-to-end integration tests cover the full ingestion-to-search flow.

Phase gate: Pattern endpoints return correct data; rollback restores a prior annotation state; full end-to-end test passes from sync trigger to search result; no P1 open findings.

---

## T18: Archive-Level Pattern Detection

Owner:      codex
Phase:      5
Type:       none
Depends-On: T07, T16

Objective: |
  Implement the pattern detection service and API: recurring themes by frequency,
  theme co-occurrence, theme timeline, and LLM-suggested new categories from clustering.
  All results include a disclaimer framing them as computational patterns.

Acceptance-Criteria:
  - id: AC-1
    description: "`GET /patterns/recurring` returns theme categories sorted by appearance count descending; each item has `category_id`, `name`, `count`, `percentage_of_dreams`. Verified by tests/integration/test_patterns_api.py::test_recurring_patterns_sorted_by_count."
    test: "tests/integration/test_patterns_api.py::test_recurring_patterns_sorted_by_count"
  - id: AC-2
    description: "`GET /patterns/co-occurrence` returns pairs of category_ids with co-occurrence count ≥ 2, sorted by count descending. Verified by tests/integration/test_patterns_api.py::test_co_occurrence_minimum_threshold."
    test: "tests/integration/test_patterns_api.py::test_co_occurrence_minimum_threshold"
  - id: AC-3
    description: "`GET /patterns/timeline?theme_id=<id>` returns a list of `{date, salience}` objects for all confirmed dream themes with that category_id, sorted by date ascending. Verified by tests/integration/test_patterns_api.py::test_theme_timeline_sorted_by_date."
    test: "tests/integration/test_patterns_api.py::test_theme_timeline_sorted_by_date"
  - id: AC-4
    description: "Every response from `/patterns/*` includes `{\"interpretation_note\": \"These are computational patterns, not authoritative interpretations.\", \"generated_at\": \"<ISO8601>\"}`. Verified by tests/integration/test_patterns_api.py::test_patterns_include_disclaimer."
    test: "tests/integration/test_patterns_api.py::test_patterns_include_disclaimer"

Files:
  - app/services/patterns.py
  - app/api/patterns.py
  - tests/integration/test_patterns_api.py

Notes: |
  Pattern queries use only `status='confirmed'` dream themes. Draft and rejected themes
  are excluded from all pattern computations.
  `/patterns/suggested-categories` is a separate endpoint using an LLM call;
  implement only if time allows in Phase 5, otherwise defer to v2.

---

## T19: Annotation Versioning and Rollback

Owner:      codex
Phase:      5
Type:       none
Depends-On: T07, T16

Objective: |
  Implement the rollback service that restores any entity (DreamTheme, ThemeCategory)
  to a prior state captured in AnnotationVersion. Expose rollback via API.
  Verify that version history is complete for all supported mutations.

Acceptance-Criteria:
  - id: AC-1
    description: "`GET /dreams/{id}/themes/history` returns all AnnotationVersion rows for that dream's themes in reverse-chronological order, each with: `id`, `entity_type`, `entity_id`, `snapshot`, `created_at`. Verified by tests/integration/test_versioning.py::test_history_returns_all_versions."
    test: "tests/integration/test_versioning.py::test_history_returns_all_versions"
  - id: AC-2
    description: "`POST /dreams/{id}/themes/{theme_id}/rollback/{version_id}` restores the DreamTheme record to the snapshot captured in the AnnotationVersion with that ID; returns HTTP 200 with the restored state. Verified by tests/integration/test_versioning.py::test_rollback_restores_prior_state."
    test: "tests/integration/test_versioning.py::test_rollback_restores_prior_state"
  - id: AC-3
    description: "Rollback itself writes a new AnnotationVersion snapshot (the post-rollback state), so the history remains append-only. Verified by tests/integration/test_versioning.py::test_rollback_appends_version_record."
    test: "tests/integration/test_versioning.py::test_rollback_appends_version_record"
  - id: AC-4
    description: "`AnnotationVersion` table has no DELETE or UPDATE queries in the codebase (grep for `DELETE FROM annotation_versions` and `UPDATE annotation_versions` returns 0 matches). Verified by tests/unit/test_versioning.py::test_no_delete_or_update_on_annotation_versions."
    test: "tests/unit/test_versioning.py::test_no_delete_or_update_on_annotation_versions"

Files:
  - app/services/versioning.py
  - app/api/versioning.py
  - tests/integration/test_versioning.py
  - tests/unit/test_versioning.py

Notes: |
  The rollback API endpoint requires authentication.
  Rollback does not re-run the LLM — it restores the exact snapshot from AnnotationVersion.snapshot.

---

## T20: End-to-End Integration Test

Owner:      codex
Phase:      5
Type:       none
Depends-On: T17, T18, T19

Objective: |
  Write an end-to-end integration test that covers the full ingestion-to-search path:
  trigger sync, wait for worker completion, verify dream entries stored, verify themes
  extracted, verify search returns the indexed entry. This test uses a seeded fixture
  document and a real (test) database.

Acceptance-Criteria:
  - id: AC-1
    description: "`test_full_ingestion_to_search_flow` triggers sync with a fixture document, polls until job status='done', then verifies: ≥1 DreamEntry exists, ≥1 DreamTheme with status='draft' exists, `GET /search?q=<known_keyword>` returns the entry with relevance_score > 0.3. Verified by tests/integration/test_e2e.py::test_full_ingestion_to_search_flow."
    test: "tests/integration/test_e2e.py::test_full_ingestion_to_search_flow"
  - id: AC-2
    description: "The e2e test cleans up all inserted records after completion (no leftover state between runs). Verified by tests/integration/test_e2e.py::test_e2e_cleanup_is_complete."
    test: "tests/integration/test_e2e.py::test_e2e_cleanup_is_complete"

Files:
  - tests/integration/test_e2e.py
  - tests/fixtures/seed_dreams.json

Notes: |
  The e2e test uses a fixture that mocks the Google Docs API call (returns seeded content).
  The real Anthropic API is called only if ANTHROPIC_API_KEY is present; otherwise the LLM
  step uses a fixture response. This avoids cost in CI while still covering the full path.
  This task is the final phase gate task for the project.

---

## Phase 6: Universal Source Intake and Parser Profiles ✅ Complete (2026-04-21)

Goal: Replace the one-source-one-format assumption with a reliable ingestion architecture that can read from multiple source containers, normalize heterogeneous documents, resolve parser profiles deterministically, and only then perform segmentation, enrichment, embeddings, and indexing.

Phase gate: Source discovery, normalization, parser-profile resolution, provenance persistence, and downstream ingestion all operate through the canonical pipeline defined in docs/spec.md §12. No ingestion path is allowed to bypass normalization or parser-profile attribution.

---

## T21: Source Connector Abstraction and Provenance Model

Owner:      codex
Phase:      6
Type:       rag:ingestion
Depends-On: T17, T20

Objective: |
  Introduce a source connector abstraction that separates source discovery/fetch from dream parsing.
  The first target shape must support both a single Google Doc and a folder-like container of multiple source documents.

Acceptance-Criteria:
  - id: AC-1
    description: "A connector interface exists that can enumerate source documents and fetch their raw contents without invoking segmentation logic. Verified by tests/unit/test_source_connectors.py::test_connector_interface_separates_discovery_from_parsing."
    test: "tests/unit/test_source_connectors.py::test_connector_interface_separates_discovery_from_parsing"
  - id: AC-2
    description: "Connector output includes stable provenance fields: `source_type`, `external_id`, `title`, `source_path`, and `updated_at` when available. Verified by tests/unit/test_source_connectors.py::test_connector_preserves_provenance_fields."
    test: "tests/unit/test_source_connectors.py::test_connector_preserves_provenance_fields"
  - id: AC-3
    description: "The existing single-document Google Docs path is adapted to the connector interface without changing downstream dream analysis behavior. Verified by tests/integration/test_source_connectors.py::test_single_doc_connector_matches_existing_fetch_behavior."
    test: "tests/integration/test_source_connectors.py::test_single_doc_connector_matches_existing_fetch_behavior"

Files:
  - app/services/gdocs_client.py
  - app/retrieval/types.py
  - app/retrieval/ingestion.py
  - tests/unit/test_source_connectors.py
  - tests/integration/test_source_connectors.py

Notes: |
  This task defines the boundary between source access and parsing.
  Do not encode dream-entry boundary logic inside any connector.

---

## T22: Normalized Document Contract

Owner:      codex
Phase:      6
Type:       rag:ingestion
Depends-On: T21

Objective: |
  Define and enforce a canonical `NormalizedDocument` contract that all connectors must emit before any parser or segmentation logic runs.

Acceptance-Criteria:
  - id: AC-1
    description: "A normalized document model exists with required fields: `client_id`, `source_type`, `external_id`, `source_path`, `title`, `raw_text`, `sections`, `metadata`, and `fetched_at`. Verified by tests/unit/test_normalized_document.py::test_normalized_document_requires_canonical_fields."
    test: "tests/unit/test_normalized_document.py::test_normalized_document_requires_canonical_fields"
  - id: AC-2
    description: "Source-native responses are converted to `NormalizedDocument` before any dream segmentation or enrichment path executes. Verified by tests/unit/test_normalized_document.py::test_segmentation_rejects_non_normalized_input."
    test: "tests/unit/test_normalized_document.py::test_segmentation_rejects_non_normalized_input"
  - id: AC-3
    description: "Normalization preserves raw source text and section boundaries without adding retrieval or embedding side effects. Verified by tests/integration/test_normalized_document.py::test_normalization_is_side_effect_free."
    test: "tests/integration/test_normalized_document.py::test_normalization_is_side_effect_free"

Files:
  - app/retrieval/types.py
  - app/services/segmentation.py
  - app/retrieval/ingestion.py
  - tests/unit/test_normalized_document.py
  - tests/integration/test_normalized_document.py

Notes: |
  This task establishes the only legal handoff shape from connectors to parsers.
  No downstream code may depend on raw Google SDK payloads after this task lands.

---

## T23: Parser Profiles and Resolution Policy

Owner:      codex
Phase:      6
Type:       rag:ingestion
Depends-On: T22

Objective: |
  Implement parser profiles as explicit strategies that transform `NormalizedDocument`
  into `DreamEntryCandidate` objects. Add a profile resolver that prefers operator-configured
  profiles and uses heuristic auto-detection only as a fallback.

Acceptance-Criteria:
  - id: AC-1
    description: "At least three parser profiles exist: `default`, `dated_entries`, and `heading_based`, each returning `DreamEntryCandidate` objects from the same normalized input contract. Verified by tests/unit/test_parser_profiles.py::test_profile_registry_contains_required_profiles."
    test: "tests/unit/test_parser_profiles.py::test_profile_registry_contains_required_profiles"
  - id: AC-2
    description: "When an explicit profile is configured for a source or client, the resolver uses it even if heuristics prefer a different profile. Verified by tests/unit/test_parser_profiles.py::test_explicit_profile_overrides_autodetect."
    test: "tests/unit/test_parser_profiles.py::test_explicit_profile_overrides_autodetect"
  - id: AC-3
    description: "When no explicit profile is configured, the resolver selects the highest-confidence profile or falls back to `default` with a warning when confidence is below threshold. Verified by tests/unit/test_parser_profiles.py::test_low_confidence_autodetect_falls_back_to_default."
    test: "tests/unit/test_parser_profiles.py::test_low_confidence_autodetect_falls_back_to_default"
  - id: AC-4
    description: "Profile resolution and parse output record the applied profile name and parse warnings for later review. Verified by tests/integration/test_parser_profiles.py::test_ingestion_persists_applied_profile_and_warnings."
    test: "tests/integration/test_parser_profiles.py::test_ingestion_persists_applied_profile_and_warnings"

Files:
  - app/services/segmentation.py
  - app/retrieval/types.py
  - app/retrieval/ingestion.py
  - tests/unit/test_parser_profiles.py
  - tests/integration/test_parser_profiles.py

Notes: |
  Parser profiles may use deterministic heuristics first and narrowly scoped LLM assistance only for ambiguous boundaries.
  A profile must never perform network fetch, embedding generation, or DB writes.

---

## T24: Ingestion Pipeline Refactor to Canonical Stages

Owner:      codex
Phase:      6
Type:       rag:ingestion
Depends-On: T23

Objective: |
  Refactor ingestion so that downstream analysis, embeddings, and indexing start only after the canonical stages complete:
  source discovery -> normalization -> profile resolution -> candidate generation -> validation -> persistence.

Acceptance-Criteria:
  - id: AC-1
    description: "The ingestion service processes source documents through the canonical staged pipeline in order, with no stage skipping. Verified by tests/integration/test_ingestion_pipeline.py::test_ingestion_uses_canonical_stage_order."
    test: "tests/integration/test_ingestion_pipeline.py::test_ingestion_uses_canonical_stage_order"
  - id: AC-2
    description: "Embeddings and retrieval indexing are not invoked for documents that fail normalization or candidate validation. Verified by tests/integration/test_ingestion_pipeline.py::test_invalid_documents_do_not_reach_embedding_stage."
    test: "tests/integration/test_ingestion_pipeline.py::test_invalid_documents_do_not_reach_embedding_stage"
  - id: AC-3
    description: "Re-ingesting an unchanged source document is idempotent by `external_id` plus content hash, and does not duplicate dream entries or chunks. Verified by tests/integration/test_ingestion_pipeline.py::test_reingest_is_idempotent_under_normalized_pipeline."
    test: "tests/integration/test_ingestion_pipeline.py::test_reingest_is_idempotent_under_normalized_pipeline"

Files:
  - app/retrieval/ingestion.py
  - app/workers/ingest.py
  - app/workers/index.py
  - tests/integration/test_ingestion_pipeline.py

Context-Refs:
  - docs/spec.md §12

Notes: |
  This task is the semantic ownership boundary for future ingestion work.
  Any shortcut from connector output straight into embeddings or indexing is a design regression.

---

## T25: Operator Controls, Reviewability, and Folder Intake Readiness

Owner:      codex
Phase:      6
Type:       rag:ingestion
Depends-On: T24

Objective: |
  Add operator-facing controls for source selection and parser profile assignment, plus reviewable diagnostics for low-confidence parses and folder-level discovery.

Acceptance-Criteria:
  - id: AC-1
    description: "Operator config can assign a parser profile explicitly to a source container or client, and ingestion uses that assignment on the next run. Verified by tests/integration/test_ingestion_controls.py::test_operator_profile_assignment_applied_on_next_ingest."
    test: "tests/integration/test_ingestion_controls.py::test_operator_profile_assignment_applied_on_next_ingest"
  - id: AC-2
    description: "Low-confidence parse results are surfaced as structured warnings with source provenance and applied profile, rather than silently treated as high-confidence truth. Verified by tests/integration/test_ingestion_controls.py::test_low_confidence_parse_is_reviewable."
    test: "tests/integration/test_ingestion_controls.py::test_low_confidence_parse_is_reviewable"
  - id: AC-3
    description: "Folder-style intake can enumerate multiple source documents and process them through the same normalized pipeline one by one without mixing provenance. Verified by tests/integration/test_ingestion_controls.py::test_folder_intake_preserves_per_document_provenance."
    test: "tests/integration/test_ingestion_controls.py::test_folder_intake_preserves_per_document_provenance"

Files:
  - app/shared/config.py
  - app/retrieval/ingestion.py
  - app/workers/ingest.py
  - tests/integration/test_ingestion_controls.py

Context-Refs:
  - docs/spec.md §12

Notes: |
  This task does not require broad multi-tenant productization.
  The control surface may remain operator-only, but the profile decision must become explicit, persistent, and auditable.

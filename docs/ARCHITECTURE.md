# Architecture — Dream Motif Interpreter

Version: 4.1
Last updated: 2026-08-31
Status: Active — reflects the implemented runtime through migration 025

## 1. System definition

Dream Motif Interpreter is a private, single-operator dream archive and reflection system. It
combines Google Docs intake, a canonical PostgreSQL archive, grounded retrieval, bounded LLM
analysis, Telegram text/voice capture and an evidence-first motif review surface.

It is reflective journaling software, not a diagnostic or clinical system. Model output remains a
suggestion until the operator confirms it.

## 2. Runtime topology

The same repository contains separate runtime boundaries:

- FastAPI serves authenticated archive, motif, research and Dream Memory Map APIs.
- The Telegram process runs long polling, bounded assistant tools and durable maintenance loops.
- The optional auto-sync process polls lightweight Google metadata and runs ingestion after a real
  document change.
- A one-shot migration container applies Alembic before API and bot startup.
- PostgreSQL/pgvector and Redis are infrastructure dependencies.

There is no unrestricted agent loop and no runtime shell execution. Tool use is bounded to a
catalog and a maximum number of rounds.

## 3. Data ownership

| Store | Ownership |
|---|---|
| PostgreSQL | Canonical dreams, chunks, themes, motifs, annotations, sessions, feedback, graph controls, durable capture stages, voice events and delivery cursors |
| Google Docs | External intake and editable human mirror; not the transactional source of truth |
| Redis | Expiring Telegram reply targets/confirmations/displayed sets plus sync coordination |
| `VOICE_MEDIA_DIR` | Temporary raw media needed for retryable transcription |
| `RUNTIME_STATE_FILE` | Active/extra Google document identifiers and cached names; shared `flock` plus atomic replace coordinates API, bot and auto-sync |

Redis loss must never delete a dream, but it removes safe restart context for short replies such as
`да` or `к этому`. The production bot therefore verifies Redis during startup.

## 4. Telegram capture and post-processing

`AssistantFacade.create_dream()` has a deliberately small synchronous boundary:

1. Parse explicit date/title hints and remove recording commands from the body.
2. Derive a deterministic provisional title without a provider call.
3. In one PostgreSQL transaction, insert the canonical `DreamEntry` and four independent
   `DreamProcessingJob` rows: `gdocs`, `index`, `analysis` and `motif`.
4. Return a save card immediately with separate archive, processing and Google Docs states.

The Telegram maintenance supervisor continuously claims due jobs and drains them again after a
restart. Each row has a lease owner/token, bounded attempts, backoff and stale-lease recovery.
Stages do not block one another: an embeddings outage does not prevent Google Docs delivery, and a
Google API outage does not prevent search indexing.

Stage idempotency boundaries:

- `gdocs`: unique database receipt plus document-side named-range marker
- `index`: upserted chunks keyed by dream/chunk identity
- `analysis`: existing theme state is checked before provider work; writes are transactional and
  versioned
- `motif`: existing motif state is checked and errors are distinct from legitimate no-result runs

The idempotency key belongs to the ingress event, not to dream prose. A replay of the same Telegram
message reuses the dream and repairs missing stage rows; a later message with identical text is a
legitimate separate dream. An exhausted failed job requires an explicit retry, which resets its
attempt budget under database constraints.

Notes use the same durable acknowledgement boundary. The note row and independent `index` and
`gdocs` jobs commit in one transaction. The user-facing acknowledgement says the note was accepted
into the background queue; it never claims that embeddings or Google Docs already completed.
Document delivery is pinned to the target document captured when the note is created.

## 5. Google Docs ingestion and reconciliation

The intake pipeline is:

1. `GoogleDocsSourceConnector` returns a normalized source document.
2. A selected parser profile segments it into candidates.
3. Validation rejects low-integrity candidates before embeddings.
4. `_store_entries()` resolves stable source-slot identity and content identity.
5. Missing analysis/index stages run idempotently.

Source-slot identity is scoped to a document and stable heading occurrence rather than the global
paragraph index. Title/date-only edits can update the same archive row. Ambiguous body-plus-heading
changes and cross-document identical bodies are fail-closed: ingestion reports a conflict instead
of silently transferring source ownership or creating an unnoticed duplicate.

Google Docs uses UTF-16 character indices. Every insert/range calculation passes through the
UTF-16 length helper so emoji and other astral characters cannot shift later operations.

## 6. Retrieval boundary

Retrieval combines exact PostgreSQL FTS and semantic pgvector candidates:

- concrete-object queries receive an exact pass before semantic fusion
- exact archive evidence survives a query-embedding outage
- multi-token evidence must occur in the same sentence
- theme fragments are included only when conditioned on the current query
- vector-only evidence must meet at least the verified semantic floor (`0.40`)
- embedding vectors must be finite and exactly 1536-dimensional
- duplicate chunks are fused with corrected evidence offsets and a final `RESULT_LIMIT`

Database/programming errors propagate. Only the explicitly normalized embedding failure may use an
exact-evidence fallback. When no verified evidence remains, the service returns
`InsufficientEvidence` rather than inventing a result.

## 7. Telegram workflow state

Long conversation history is stored in `bot_sessions`. Short-lived interaction state is stored in
Redis with TTL and mirrored in memory for the active process:

- displayed dream sets and reply-message mappings
- pending single/batch notes
- pending dream capture confirmation
- pending interpretation consent

The handler resolves explicit reply context first and never silently substitutes the latest dream
when the referenced message is unknown. Natural capture is anchored to a dream opening, respects
negation, and separates a trailing interpretation question from the archived text.

Feedback stores a privacy-safe capsule: normalized request/response hashes and lengths, tool names,
dream IDs, build SHA, model/route and issue categories. Raw dream/request/response text is not copied
into that capsule.

## 8. Durable voice pipeline

Voice ingress is unique on `(chat_id, telegram_message_id)`:

1. Insert or resolve the durable event.
2. Download into the configured media root.
3. Persist the path before acknowledging background processing.
4. Claim the event with a database lease.
5. Transcribe with bounded retry/backoff.
6. Persist the transcript, build the assistant reply, and stage the whole reply durably.
7. Remove raw media only after durable reply staging or terminal retention handling.
8. Deliver chunks below Telegram's limit, persisting the cursor after each successful chunk.

Periodic recovery reclaims expired leases, retries `reply_pending` and transcription work, purges
expired transcripts, and removes only old orphan files inside `VOICE_MEDIA_DIR`. Multiple bot
instances cannot process the same live lease. Operational transcripts expire independently and do
not become archive dreams without an explicit save action.

## 9. Motif review and Dream Memory Map

Motif induction is separate from curated taxonomy themes. Draft motifs retain verified source
fragments. `GET /motifs/review` powers an evidence-first review inbox where the operator can:

- confirm or reject a suggestion
- rename it with version history
- return it to draft
- request external research only after confirmation

The authenticated Mini App state may contain readable dream date/title labels. Privacy exports keep
opaque source identifiers. Graph hide is reversible through an append-only `restore`; delete and
reject remain intentionally irreversible in the UI. Every privacy mutation produces a receipt.

## 10. API, authentication and observability

All data APIs require either `X-API-Key` or verified Telegram Web App init data. Public routes are
limited to `/health`, `/auth/callback` and the static Mini App shell; the shell contains no archive
data. `SECRET_KEY` must be nonblank and strong outside tests. HTTP responses are `no-store` and
carry baseline anti-sniffing/referrer/permissions headers; the Mini App additionally has a narrow
Content Security Policy that permits its Telegram bootstrap while blocking arbitrary origins.

Structured logs and OpenTelemetry spans/metrics are created across HTTP, DB and worker boundaries.
OTLP exporters activate only when `OTEL_EXPORTER_OTLP_ENDPOINT` is explicitly configured. Public
`/health` includes `BUILD_SHA` and database/index health, but is not a substitute for Redis,
provider, Telegram or outbox smoke tests.

## 11. Failure guarantees

Implemented guarantees:

- acknowledged text capture survives provider and process failure
- replay of one Telegram event and Google delivery are idempotent at the database boundary; equal
  text from a new event remains distinct
- acknowledged notes survive provider and process failure and drain from independent jobs
- due capture/voice work is recovered after restart and while the process stays alive
- raw voice deletion is constrained to the configured media root
- destructive retrieval evaluation cannot target the ordinary `DATABASE_URL`
- graph hide/restore and motif edits retain append-only history

Explicit non-guarantees:

- hosted operation and provider quota are not proven by repository CI
- Google/Telegram live semantics still require an operator smoke test
- exact-once external effects rely on provider-side/document-side idempotency markers; leases alone
  provide at-least-once execution
- semantic synonym grouping in the graph is not implemented; repeat edges use normalized labels

## 12. Main modules

| Module | Responsibility |
|---|---|
| `app/api/` | Authenticated HTTP surfaces and public health/static shell |
| `app/assistant/` | Bounded tools, capture facade, chat/session state |
| `app/retrieval/` | Chunking, embeddings, exact/semantic retrieval and evidence |
| `app/services/` | Analysis, motifs, graph controls, Google Docs and receipts |
| `app/telegram/` | Authorized polling adapter, save cards, commands and callbacks |
| `app/workers/dream_processing.py` | Leased independent post-capture stages and recovery |
| `app/workers/sync_jobs.py` | Leased manual Google Docs sync jobs and recovery |
| `app/workers/transcribe.py` | Leased transcription/reply delivery and maintenance |
| `app/workers/ingest.py` | Normalized multi-source ingestion and reconciliation |

Schema changes are append-only Alembic revisions. Current head is `026_manual_sync_jobs`.
Deployment must stop API, bot and auto-sync, run `alembic upgrade head` to completion, and only then
start application processes; `scripts/deploy_compose.sh` enforces that quiesced sequence.

## 13. Decision records

Architecture decisions live in `docs/adr/`. The implementation continues to follow the core
choices: one repository with separate process boundaries, bounded assistant tools, managed Whisper,
persisted sessions, Compose-first deployment, motifs separate from taxonomy and external research
behind an explicit trust/feature gate.
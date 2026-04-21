# Dream Motif Interpreter — Phase Plan

Version: 2.1
Last updated: 2026-04-21 (Phases 1–11 complete; local setup/testing checkpoint recorded)

## 1. Current Status: Phases 1–11 Complete

**Phases 1–5** — Backend platform complete:

- ingestion and sync foundation
- archive schema and migrations (001–006)
- theme extraction and curation
- retrieval pipeline (pgvector + HNSW)
- archive-level pattern analysis
- rollback and versioning hardening

**Phases 6–8** — Telegram interface and hardening complete:

- Telegram bot runtime with text and voice support
- bounded assistant tool-use loop
- async transcription via OpenAI Whisper
- session persistence and media lifecycle
- runbooks and operational hardening
- all open decisions resolved

**Phases 9–11** — Motif, research, and feedback layers complete:

- open-vocabulary motif induction with confirmation workflow
- external research augmentation behind explicit confirmation + feature flag
- Telegram feedback capture and feedback context injection into assistant prompts
- related migrations `009`–`011` present in the schema chain
- implementation-level fix queue from Phases 10–11 closed in prior commits

Execution graph:

- [docs/tasks_phase6.md](tasks_phase6.md) — Phase 6–8 active graph
- [docs/tasks.md](tasks.md) — historical Phase 1–5 graph
- [docs/tasks_phase9.md](tasks_phase9.md) — historical Phase 9 graph
- [docs/tasks_phase10.md](tasks_phase10.md) — historical Phase 10 graph
- [docs/tasks_phase11.md](tasks_phase11.md) — historical Phase 11 graph

## 2. Planning Principle

The correct next move is:

1. preserve Dream Motif Interpreter as the source of truth
2. add Telegram as an interface layer
3. add voice support after text interaction is stable
4. harden deployment, testing, and runbooks before widening scope

Reference implementation source for the interaction layer:

- `~/Documents/dev/ai-stack/projects/film-school-assistant`

This should be used as a working code reference for Telegram-first patterns instead of regenerating the entire interaction layer from scratch.

## 3. Phase 6 — Telegram Interaction Foundation ✓ Complete

### Objective

Add a Telegram text interface that lets the user interact with the dream archive conversationally.

### Why this phase exists

- it unlocks the highest-value interaction change with the lowest architectural regret
- it reuses the current backend instead of replacing it
- it validates whether a conversational layer actually improves archive usability

### Scope In

- Telegram bot runtime in the same repository
- bounded assistant tool facade
- text-based archive interaction
- session persistence
- explicit sync trigger
- single-user Telegram allowlist auth

Implementation rule:

- port proven interaction-layer patterns from `film-school-assistant`
- redesign only the dream-domain-specific pieces

### Scope Out

- voice-message processing
- chat-driven curation mutations
- web interface
- multi-user access

### Phase gate

- authorized Telegram text flow works end-to-end
- insufficient-evidence behavior is preserved in chat
- bot sessions survive restart
- deployment and env docs are complete enough to run privately

## 4. Phase 7 — Voice Interaction and Media Pipeline ✓ Complete

### Objective

Extend the Telegram assistant to support voice messages without weakening backend integrity.

### Why this phase is separate

- media handling and transcription add a new operational class of work
- voice needs distinct testing, retention, and failure handling
- separating it from Phase 6 reduces integration risk

### Scope In

- voice ingress
- media metadata persistence
- download + temporary storage
- async transcription
- transcript routing through the text assistant path
- media cleanup

Implementation rule:

- reuse the sequencing and ops posture proven in `film-school-assistant`
- do not import its storage schema or creative-workflow domain assumptions

### Scope Out

- general audio archive features
- long-term raw audio retention

### Phase gate

- voice note processing succeeds end-to-end
- failures are observable and recoverable
- retention and cleanup are documented and test-covered

## 5. Phase 8 — Hardening and Controlled Expansion ✓ Complete

### Objective

Stabilize the Telegram-enabled system and decide whether any curation flows belong in chat.

### Scope In

- observability for bot and transcription paths
- operational runbooks
- stronger deployment story
- controlled evaluation of read/write chat capabilities

### Scope Out

- multi-user productization
- SaaS packaging
- broad autonomous assistant behavior

### Phase gate

- deployment topology is stable
- bot/voice runbooks exist
- major open decisions are resolved
- optional mutation flows, if added, have explicit audit-safe UX

## 6. Resolved Decisions (Phase 6–8)

All decisions were resolved during implementation:

- Phase 6 is read-only plus `trigger_sync` ✓
- Transcription: OpenAI Whisper API (managed) ✓
- Telegram ingress: long polling ✓
- Session persistence: PostgreSQL `bot_sessions` table ✓
- Raw audio: immediate deletion after transcription; `VOICE_RETENTION_SECONDS` sweep ✓
- Transcript retention: not stored — transient in memory only ✓

## 7. Recommended Milestones

### M1

Telegram bot can answer text questions about the archive safely.

### M2

Bot can trigger sync and survive restart without losing active session integrity.

### M3

Voice messages work through async transcription and the same assistant path.

### M4

Deployment docs, env docs, runbooks, and tests cover the Telegram-enabled stack.

## 8. Current Checkpoint and Next Start Point

- Local setup checkpoint is complete: `.venv` exists, local Postgres/Redis are reachable, Alembic is at head, and `/health` was verified.
- Google Docs auth no longer depends only on OAuth env vars; the code now supports `GOOGLE_SERVICE_ACCOUNT_FILE` as an alternative credential path.
- The next runtime checkpoint is a live Google Docs fetch with a real `GOOGLE_DOC_ID`.
- The next testing checkpoint is a full pytest run inside `.venv`; local collection now succeeds with `295` tests.
- Chat-driven curation mutations remain deferred. See [Telegram Interaction Model §11](TELEGRAM_INTERACTION_MODEL.md) for preconditions required before enabling.
- Do not open "Phase 12" preemptively. Start a maintenance/fix phase only if the live ingestion verification or full test pass exposes concrete defects worth batching.

## 9. Phase 9 — Motif Abstraction and Induction

### Objective

Given a dream entry, inductively derive higher-order abstract motifs from concrete imagery without using a predefined taxonomy.

### Why this phase exists

- the existing theme extraction pipeline assigns dreams to a closed vocabulary of curated categories
- that closed vocabulary is useful for pattern queries but cannot surface novel, emergent imagery
- motif induction produces open-vocabulary labels that describe what is actually present without forcing a match to known categories
- these labels coexist with taxonomy-based themes; they are stored separately and serve a different analytical purpose

### Scope In

- `ImageryExtractor`: extracts concrete imagery fragments from dream text
- `MotifInductor`: forms abstract motif labels from extracted imagery (open vocabulary, model-derived)
- `MotifGrounder`: verifies imagery fragments against source offsets (reuses offset-verification pattern from `Grounder`)
- `MotifService`: orchestrates the induction pipeline; wired into ingest when `MOTIF_INDUCTION_ENABLED=true`
- New table: `motif_inductions` (columns: `id`, `dream_id`, `label`, `rationale`, `confidence`, `status`, `fragments` JSONB, `model_version`, `created_at`)
- New migration: `009_add_motif_inductions`
- New API routes: `GET /dreams/{id}/motifs`, `PATCH /dreams/{id}/motifs`, `GET /dreams/{id}/motifs/history`
- New assistant tool: `get_dream_motifs`
- New env var: `MOTIF_INDUCTION_ENABLED` (default `false`)

### Scope Out

- merging inducted motifs into the `dream_themes` table or `theme_categories` taxonomy
- treating inducted motif labels as interpretations
- automated curation without human confirmation

### Workstreams

- WS-9.1: DB migration and ORM models (`motif_inductions`, `AnnotationVersion` support)
- WS-9.2: `ImageryExtractor` + `MotifInductor` LLM pipeline
- WS-9.3: `MotifGrounder` (reuses offset-verification from `Grounder`)
- WS-9.4: `MotifService` orchestrator + ingest integration (`MOTIF_INDUCTION_ENABLED` flag)
- WS-9.5: API routes (`app/api/motifs.py`)
- WS-9.6: assistant tool `get_dream_motifs` + facade method + system prompt update
- WS-9.7: pattern queries extension (optional, depends on WS-9.4)

### Phase gate

- induction pipeline runs end-to-end for a dream entry when `MOTIF_INDUCTION_ENABLED=true`
- inducted motifs are stored in `motif_inductions`, never in `dream_themes`
- `GET /dreams/{id}/motifs` returns motifs with confidence and status fields
- assistant can present motifs with correct confidence framing
- feature flag disables the pipeline completely when set to `false`

### Status: Complete

See [docs/tasks_phase9.md](tasks_phase9.md) for the detailed task graph.
See [docs/MOTIF_ABSTRACTION.md](MOTIF_ABSTRACTION.md) for conceptual documentation.
See [docs/adr/ADR-008-motif-induction-vs-taxonomy.md](adr/ADR-008-motif-induction-vs-taxonomy.md).

## 10. Phase 10 — Research Augmentation

### Objective

On demand, search for mythology, folklore, cultural, and taboo parallels to confirmed inducted motifs from external sources.

### Why this phase exists

- inducted motifs may have structural parallels in comparative mythology and folklore that are not in the local archive
- surfacing these parallels enriches analysis without conflating external content with archive evidence
- all external results carry an explicitly low trust level and are always labeled as speculative

### Scope In

- `app/research/retriever.py` (`ResearchRetriever`): calls external search API
- `app/research/synthesizer.py` (`ResearchSynthesizer`): summarises retrieved results into labeled parallels
- New table: `research_results` (columns: `id`, `motif_id`, `dream_id`, `query_label`, `parallels` JSONB, `sources` JSONB, `triggered_by`, `created_at`)
- New migration: `010_add_research_results`
- New assistant tool: `research_motif_parallels` (requires user confirmation before executing)
- New env vars: `RESEARCH_AUGMENTATION_ENABLED` (default `false`), `RESEARCH_API_KEY`
- Trust constraint: all research output confidence values are `speculative`, `plausible`, or `uncertain` — never `high` or `confirmed`; always labeled as external and unverified

### Scope Out

- treating external results as authoritative
- automating research without user request
- storing research results in the dream archive tables
- using research results to drive curation decisions

### Dependencies

- Phase 9 must be complete (`motif_inductions` table must exist; research requires confirmed inducted motifs)

### Phase gate

- `research_motif_parallels` tool requires explicit user confirmation before executing
- all returned parallels carry source URL and retrieval timestamp
- confidence vocabulary is limited to `speculative`, `plausible`, `uncertain`
- feature flag disables the tool completely when set to `false`

### Status: Complete

See [docs/RESEARCH_AUGMENTATION.md](RESEARCH_AUGMENTATION.md) for full design documentation.
See [docs/adr/ADR-009-research-trust-boundary.md](adr/ADR-009-research-trust-boundary.md).

## 11. Phase 11 — Feedback Loop

### Objective

Allow the user to rate assistant responses on a 1–5 scale with an optional comment, providing a quality signal for human review.

### Why this phase exists

- the bounded tool-use loop produces assistant responses whose quality cannot currently be measured
- a lightweight rating mechanism provides a signal for manual review without requiring automated retraining infrastructure
- feedback is captured passively in Telegram without adding a separate workflow step

### Scope In

- New model: `assistant_feedback` (columns: `id`, `chat_id`, `context` JSONB, `score`, `comment`, `created_at`)
- New migration: `011_add_feedback`
- Telegram UX: a digit-only reply (1–5) sent immediately after a substantive assistant response is captured as a rating
- New API route: `GET /feedback` (admin paginated view)

### Scope Out

- automated retraining or fine-tuning pipelines
- using feedback scores to alter model behavior automatically
- unsupervised training or reinforcement from feedback without explicit human review
- multi-user feedback aggregation

### Dependencies

- independent of Phases 9 and 10

### Phase gate

- digit-only replies (1–5) are captured as ratings linked to the preceding assistant response context
- ratings are retrievable via `GET /feedback`
- the system does not alter model behavior based on ratings

### Status: Complete

See [docs/FEEDBACK_LOOP.md](FEEDBACK_LOOP.md) for full design documentation.

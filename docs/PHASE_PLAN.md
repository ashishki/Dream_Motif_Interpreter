# Dream Motif Interpreter — Phase Plan

Version: 2.3
Last updated: 2026-04-24 (Phases 13–14 planned — UX and feature backlog from Тест 2)

## 1. Current Status: Phases 1–12 Complete; Phases 13–14 Planned

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
- [docs/tasks_phase12.md](tasks_phase12.md) — historical Phase 12 graph (UX fixes, complete)
- [docs/tasks_phase13.md](tasks_phase13.md) — **planning** Phase 13 graph (multi-source, search recall)
- [docs/tasks_phase14.md](tasks_phase14.md) — **planning** Phase 14 graph (write to Google Docs)

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
- Chat-driven curation mutations remain deferred. See [Telegram Interaction Model §11](TELEGRAM_INTERACTION_MODEL.md) for preconditions required before enabling.
- Phase 12 is complete. See [docs/PHASE12_RELEASE_NOTES.md](PHASE12_RELEASE_NOTES.md).
- Phase 13 is planned. See [docs/tasks_phase13.md](tasks_phase13.md) for the full backlog.
- Phase 14 is planned. See [docs/tasks_phase14.md](tasks_phase14.md). Requires developer credential setup (WS-14.1) before coding starts.

## 12. Phase 12 — UX Quality Fixes (Тест 1)

### Objective

Fix UX-level defects identified in first real-use test session (Тест 1, 22.04.26).
No schema changes required for most items.

### Scope In

- Expose motif UUID in `get_dream_motifs` output so `research_motif_parallels` can be called
- Prohibit markdown (`**`) in assistant responses; enforce plain-text formatting
- Add dream text preview and themes to `list_recent_dreams` output
- Add dream title to `search_dreams` results; use verbal connection strength labels
- Strip `*` and `<` artifacts from `get_dream` raw text output
- Expand trigger phrases for `create_dream`; fix title resolution format
- Simplify mythological parallels flow: no verbose preamble, no "архетип", no summary paragraph
- Unify search results as single numbered list with inline connection strength
- (P2) Add `manage_archive_source` tool for changing Google Doc ID from chat

### Scope Out

- Schema changes (no new migrations expected)
- New LLM pipeline stages
- Multi-user features

### Phase gate

See [docs/tasks_phase12.md §4](tasks_phase12.md).

### Status: Complete — 2026-04-23

See [docs/tasks_phase12.md](tasks_phase12.md) for the detailed task graph.
See [docs/PHASE12_RELEASE_NOTES.md](PHASE12_RELEASE_NOTES.md) for release notes.

## 13. Phase 13 — Multi-source, Search Recall, UX Polish (Тест 2)

### Objective

Fix defects and gaps identified in Тест 2 (23.04.26): multi-source Google Docs support,
improved search recall for specific words/images, exact quote extraction, and UX polish.

### Why this phase exists

- The second Google Doc added by the user is not being searched (manage_archive_source replaces, does not add)
- search_dreams misses valid matches due to RESULT_LIMIT=5 and relevance threshold
- No tool exists for exact word/image search with Russian morphology and no threshold cutoff
- Multiple matching fragments from the same dream are hidden by the result cap
- Rating prompt is in English; terminology "архив/база" confuses internal DB with Google Docs

### Scope In

- Multi-source support: GOOGLE_DOC_IDS list in Settings; trigger_sync iterates all doc IDs
- manage_archive_source: add actions 'list', 'add', 'remove' for multi-doc management
- Terminology normalization: SYSTEM_PROMPT instructs bot to treat "архив/база" as Google Docs
- Rating prompt localization (English → Russian)
- New tool `search_dreams_exact`: pure FTS, no threshold, limit 20, Russian morphology
- Quote extraction: exact sentence from chunk_text containing the searched word
- Increase RESULT_LIMIT from 5 to 20; group multiple fragments per dream in output
- SYSTEM_PROMPT updates for new tools and formats

### Scope Out

- Schema changes
- Write to Google Docs (Phase 14)
- Multi-user features

### Phase gate

See [docs/tasks_phase13.md §4](tasks_phase13.md).

### Status: Planning — 2026-04-24

See [docs/tasks_phase13.md](tasks_phase13.md) for the detailed task graph.

## 14. Phase 14 — Write to Google Docs (Bidirectional Sync)

### Objective

Enable the bot to write newly recorded dreams into Google Docs, completing the bidirectional
sync loop so the user's journal stays up to date without manual copy-paste.

### Why this phase exists

- create_dream (Phase 11) records dreams in the internal DB only
- Тест 2 confirmed this is a critical missing feature: "Функция добавления сна в гугл документ через бот не работает. Это очень важная функция!"
- The limitation is credentials: current service account has read-only Google Docs scope
- Developer must upgrade credentials to write scope (WS-14.1) before any coding can proceed

### Scope In

- Developer setup: service account or OAuth2 credentials with write scope (WS-14.1, dev task)
- GDocsClient.append_text: insert text at end of document via batchUpdate API
- write_dream_to_google_doc in AssistantFacade
- Integrate into create_dream flow: auto-write after DB insert; report status to user
- SYSTEM_PROMPT update: describe bidirectional sync; remove outdated "requires developer" message

### Scope Out

- Schema changes
- Editing or deleting existing Google Doc content
- Multi-document write routing per dream (always writes to primary doc)

### Dependencies

- WS-14.1 (credentials) is a developer prerequisite and blocks all other workstreams
- Phases 1–13 must be complete

### Phase gate

See [docs/tasks_phase14.md §5](tasks_phase14.md).

### Status: Planning — 2026-04-24 (blocked on WS-14.1 developer credential setup)

See [docs/tasks_phase14.md](tasks_phase14.md) for the detailed task graph.

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

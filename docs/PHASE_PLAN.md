# Dream Motif Interpreter — Phase Plan

Version: 2.0
Last updated: 2026-04-15 (Phase 8 complete — all phases 1–8 done)

## 1. Current Status: Phases 1–8 Complete

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

Execution graph:

- [docs/tasks_phase6.md](tasks_phase6.md) — Phase 6–8 active graph
- [docs/tasks.md](tasks.md) — historical Phase 1–5 graph

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

## 8. Open Items

- Google Docs auth: current code path uses OAuth env vars. Service-account JSON is not yet wired; treat as a future implementation decision if adopted.
- Chat-driven curation mutations remain deferred. See [Telegram Interaction Model §11](TELEGRAM_INTERACTION_MODEL.md) for preconditions required before enabling.

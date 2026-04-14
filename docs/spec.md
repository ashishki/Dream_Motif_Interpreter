# Feature Specification — Dream Motif Interpreter

Version: 2.0  
Last updated: 2026-04-14  
Status: Current backend spec plus Phase 6+ interface roadmap

## 1. Overview

Dream Motif Interpreter is a single-user analytical system for a private dream journal.
It ingests dreams, stores them as a structured archive, extracts and curates themes, supports semantic retrieval, and surfaces archive-level patterns.

Today the implemented product is backend-first.
The next planned evolution adds a Telegram assistant layer for text and voice interaction.

## 2. Product Boundaries

### In Scope Today

- Google Docs ingestion
- dream segmentation
- theme extraction and grounding
- semantic and thematic retrieval
- curation and rollback
- archive-level pattern analysis

### In Scope for Phase 6+

- Telegram text interaction
- bounded conversational assistant behavior
- voice-message ingestion and transcription
- private single-user Telegram access

### Explicitly Out of Scope

- multi-user journals
- public SaaS posture
- clinical or therapeutic authority
- autonomous open-ended agents
- web-primary product expansion before Telegram interaction is proven

## 3. User Roles

| Role | Description | Current permissions | Planned Phase 6+ posture |
|------|-------------|---------------------|--------------------------|
| Owner | journal author and primary user | full backend access | same |
| Curator | same user acting in curation context | theme confirmation, rejection, category approval, rollback | same, but chat access to these actions is initially deferred |

## 4. Current Backend Feature Areas

### 4.1 Journal Ingestion and Sync

- fetch source document from Google Docs
- segment into dream entries
- enqueue or perform downstream analysis/indexing through the backend pipeline
- expose sync status

### 4.2 Theme Extraction and Curation

- draft theme assignment
- explicit confirm/reject flow
- annotation versioning before mutation
- rollback support

### 4.3 Retrieval

- hybrid lexical + embedding retrieval
- metaphor-aware query expansion
- `insufficient_evidence` path when evidence is weak

### 4.4 Archive-Level Patterns

- recurring motifs
- co-occurrence pairs
- per-theme timeline

## 5. Phase 6 — Telegram Text Interaction Foundation

### Objective

Make Dream Motif Interpreter usable as a conversational assistant through Telegram text without changing the core archive ownership model.

### Scope In

- Telegram bot runtime
- allowlisted single-user access
- persisted bot session state
- bounded internal tool-calling assistant
- read-oriented archive queries
- explicit sync trigger

### Scope Out

- voice messages
- chat-driven curation mutations
- generalized memory platform behavior
- web UI

### Recommended Acceptance Direction

1. The allowed Telegram user can ask natural-language questions about the dream archive.
2. The bot can search and summarize archive-backed results.
3. If evidence is weak, the bot responds with an insufficient-evidence message instead of inventing a conclusion.
4. The bot can trigger a backend sync explicitly.
5. Unauthorized Telegram users are rejected or ignored safely.

## 6. Phase 7 — Voice Interaction and Media Pipeline

### Objective

Extend the Telegram assistant to support voice messages through an async transcription pipeline.

### Scope In

- voice-message intake
- media metadata persistence
- download and temporary storage
- transcription job
- transcript handoff into the same assistant path as text
- media cleanup and retention policy

### Scope Out

- broad multimodal analysis beyond speech-to-text
- long-term raw audio retention

### Recommended Acceptance Direction

1. The bot acknowledges voice processing immediately.
2. Voice messages are transcribed asynchronously and routed through the normal assistant flow.
3. Media cleanup occurs on a documented schedule.
4. Transcription failures are observable and recoverable.

## 7. Phase 8 — Operational Hardening and Productization

### Objective

Harden the Telegram-enabled system operationally and decide whether any curation actions are safe to expose in chat.

### Scope In

- deployment finalization
- observability and runbooks
- stronger session and failure handling
- optional narrowly scoped chat curation commands after explicit review

### Scope Out

- multi-user support
- SaaS packaging
- uncontrolled assistant autonomy

## 8. Telegram Assistant Requirements

The planned Telegram assistant must:

- behave as a bounded assistant, not an unrestricted chat agent
- use explicit internal tools or service calls
- preserve Dream Motif Interpreter’s interpretation framing
- avoid pretending to know more than the archive supports
- preserve current backend quality guarantees where practical

## 9. Voice Pipeline Requirements

The planned voice path must:

- keep raw audio retention short
- avoid mixing media artifacts with canonical dream data
- make transcription provider choice explicit
- expose operational failure states clearly

## 10. Auth and Security Requirements

- current API-key auth remains for HTTP clients
- Telegram access is single-user and allowlisted
- mutation operations in chat are deferred or explicitly gated
- secrets remain environment-driven

## 11. Google Docs Credential Note

Current code expects Google Docs credentials via environment variables.
An operator may already possess a service-account JSON file with document access granted to that account.
That setup is relevant to implementation planning, but service-account auth should not be described as already implemented unless the code changes to support it.

## 12. Non-Goals for Phase 6-8

- turning the repo into a Telegram-only script
- replacing PostgreSQL with a lighter bot-local store
- merging in another product’s schema or UX mechanically
- turning chat history into canonical dream memory

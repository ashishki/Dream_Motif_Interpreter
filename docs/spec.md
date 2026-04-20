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

## 12. Future Source Intake and Normalization Direction

The current implementation assumes a single configured Google Doc as the source of truth.
That is sufficient for the present single-user archive, but it is not the long-term ingestion model.

Future ingestion work must treat source access, format parsing, and archive enrichment as separate concerns.
The canonical future pipeline is:

`source connector -> normalized document -> parser profile -> dream entry candidates -> validated dream entries -> embeddings/indexing`

### 12.1 Why this separation is required

Different operators or future customers may keep dream material in different source formats:

- one Google Doc containing many entries
- a Google Drive folder containing multiple docs
- freeform journals with weak date structure
- heading-based records
- exports from other note systems

If source-specific assumptions leak directly into segmentation, embedding, or indexing code, each new format will force risky ingestion rewrites.
That coupling is explicitly disallowed in future work.

### 12.2 Canonical internal normalization contract

All source connectors must produce a normalized intermediate document shape before any dream segmentation logic runs.

Required normalized document fields:

- `client_id`
- `source_type`
- `external_id`
- `source_path`
- `title`
- `raw_text`
- `sections`
- `metadata`
- `fetched_at`

All dream segmentation logic must consume the normalized contract, not raw Google SDK responses or source-native structures.

### 12.3 Parser profile model

Different input formats must be handled through parser profiles rather than ad hoc conditionals spread across the pipeline.

A parser profile is a deterministic strategy that:

- declares the format shape it expects
- optionally provides a confidence score or `matches()` heuristic
- transforms a normalized document into `DreamEntryCandidate` objects
- emits parse warnings and confidence markers for ambiguous boundaries

Parser profiles must not perform:

- source discovery
- network I/O
- embedding generation
- retrieval indexing
- database persistence

### 12.4 Profile selection policy

Future ingestion must support a hybrid resolution rule:

1. explicit operator-configured profile for a source or client, if present
2. heuristic auto-detection only when no explicit profile is configured
3. fallback to a conservative default profile when confidence is low
4. mark low-confidence parses as reviewable rather than silently treating them as high-confidence truth

Automatic profile selection may assist onboarding, but explicit profile assignment remains the preferred operational mode.

### 12.5 Connector policy

Source connectors are responsible only for discovery and document fetch.
They may enumerate files inside a Google Drive folder or other storage boundary, but they must not decide dream-entry boundaries.

All connector outputs must preserve provenance:

- source connector name
- original external id
- original title
- original update timestamp when available
- source location within a folder or hierarchy when available

### 12.6 Reliability requirements for future ingestion work

Any future universal ingestion implementation must preserve the following guarantees:

- idempotent re-ingestion by stable source identifiers and content hashes
- parser-profile attribution stored alongside ingestion results
- parse warnings captured without leaking secrets or raw credential material
- ambiguous records can be quarantined or flagged without blocking the entire corpus
- downstream embedding/indexing only starts after normalization and parse validation complete

### 12.7 Non-goals of this roadmap

This roadmap does not imply:

- uncontrolled multi-tenant SaaS behavior
- automatic support for every arbitrary file format on day one
- LLM-only boundary detection as the primary ingestion strategy
- mixing source-discovery logic with retrieval semantics

## 13. Non-Goals for Phase 6-8

- turning the repo into a Telegram-only script
- replacing PostgreSQL with a lighter bot-local store
- merging in another product’s schema or UX mechanically
- turning chat history into canonical dream memory

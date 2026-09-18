# Kolia Experience V1

Status: code implemented and synthetic verification completed; release candidate, not deployed or user-validated.
Date: 2026-09-18
Baseline: main at 1d8b61151556b02a4ad34a60a9b2919f14adad57.
Branch: codex/kolia-experience-v1. Never merge or change main without explicit approval.

## Product outcome

Make the existing single-operator archive useful to Nikolai, a nontechnical Jungian therapist. Success is a completed archive task, not the number of tools, a bigger graph, or multi-user readiness. The next question should concern his material rather than how to operate the bot. This is an engineering release candidate until observed with the operator.

## Preserve

- Existing canonical capture, durable jobs, source identity, voice recovery, confirmed/rejected motif history, authorization and provider-consent boundaries.
- Text and voice capture in Telegram; Google Docs remains useful for longer reading/editing. A Mini App must not be required for ordinary chat tasks.
- Human codes are ordinary #notes. Multiple codes are allowed. AI only suggests; nothing is automatically accepted, and an unclicked suggestion is not a rejection.
- Archive text, human notes and generated hypotheses remain distinct. No diagnostic or authoritative interpretation claims.
- No private archive, recordings, provider outputs, credentials or sensitive query text in public fixtures, logs or artifacts.

## Core journeys and acceptance

1. Capture a dream, including a short or backdated dream. A concise receipt confirms durable save; delayed Google Docs delivery never implies lost data. Preserve current idempotency and negation rules.
2. Find material in ordinary Russian. Results have readable dates/titles, exact evidence and full-text controls. The system explains limited coverage without requiring the user to choose a technical search mode.
3. Continue an investigation: open the second result, remove an irrelevant result, compare the remaining selection, ask a follow-up. Ordinals always refer to the visible ordered selection, never an intermediate retrieval batch. Preserve scope across restart; expired or unavailable state must not be guessed.
4. Add a note/code to the intended dream. Keep current reply targeting and batch preview/confirmation. Do not mutate archive content when modifying a working selection.
5. Investigate a selected set or period. Bound work, inspect actual source material, separate observations from hypotheses and explicitly disclose any unprocessed material. A budget limit must end with a useful final answer, not a planning fragment.
6. Review suggestions beside verified evidence. Keep confirm/rename/exclude/restore decisions. The review queue must reach older pending items and show truthful counts.
7. Use the visual workspace as an optional aid: accessible mobile layout, obvious first action, archive/search, review and resumable reading. Do not expose secrets, internal IDs or misleading delete semantics.

## Delivery slices

- S1: selection identity, turn-level accumulation and safe persistence; ordinal/selection continuation; regression coverage for several retrieval calls and restart.
- S2: bounded research/answer completion; truthful coverage; privacy-safe errors and telemetry; tests for exhaustion, truncation and unavailable evidence.
- S3: task-first optional workspace, complete paginated motif review and readable onboarding; browser/JavaScript and API tests.
- S4: updated user guide, scenario fixtures, release checklist, exact handoff and evidence. Document separately any work that requires live credentials or operator judgement.

Each logical slice is committed separately and its actual verification is recorded. Do not declare the whole vision implemented merely because the plan or helper code exists.

## Deferred, not release blockers for one operator

Tenant scaling, public registration, billing, collaborative archives, a new graph database and a provider/model rewrite. A full source-text editor, long-lived named investigation library and autonomous period reports require separate acceptance if not delivered here; existing safe paths must not be advertised as those features.

## Validation gates

Keep the full existing CI suite. Add authored-synthetic regression scenarios for multi-search union, displayed order, empty/ambiguous continuation, cancellation, restart, tool budget exhaustion, partial evidence and review pagination. Use no production credentials in CI. Code-level tests do not certify live search/model quality.

Operator acceptance remains a separate gate: on his phone, Nikolai completes capture, search, full text, follow-up comparison and note addition without being coached on commands. Record task success, interventions, lost context and desire to continue; do not invent a satisfaction score. Deploy only after branch review and an explicit rollout decision, using the existing systemd runbook and backup/restore preflight.


## Delivered implementation

S1/S2: explicit ordered selection metadata and read-only continuation commands;
turn-level candidate accumulation; conservative ordinal binding; restart-safe TTL
context; final read-only completion after tool budget exhaustion; truncation
notices; structured archive research with exact quote validation and actual
coverage; explicit human #codes; staged voice-selection publication after reply
delivery. Existing capture/durable jobs/interpretation approval stay in place.

S3: archive-first mobile workspace, paged recent/period archive, POST semantic
search, verbatim reader, separate human notes/codes, preserved draft on unknown
save outcome, selected-source research and privacy-confirmed text export;
complete paginated motif review with global counts. Graph is optional. Stale
requests cannot replace a newer view; requests have bounded waits.

S4: USER_GUIDE_RU, KOLIA_EXPERIENCE_ACCEPTANCE_RU, ADR-012, executable offline
browser smoke and focused unit/HTTP/PTB scenarios. See the current handoff for
verification evidence and remaining live acceptance. No real operator results
or satisfaction claims have been invented.

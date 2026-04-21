# Testing Strategy

Last updated: 2026-04-21

## 1. Current Testing Posture

Dream Motif Interpreter already has a stronger backend testing posture than many small assistant projects:

- unit tests
- integration tests
- migration tests
- retrieval tests
- end-to-end seeded backend flow tests
- Telegram bot tests
- voice pipeline tests
- motif/research/feedback tests

This should remain a project strength during Phase 6+.

Current local checkpoint:

- targeted setup-sensitive tests passed: `tests/unit/test_config.py` (`8 passed`), `tests/unit/test_gdocs_client.py` (`7 passed`)
- `.venv/bin/pytest --collect-only -q` currently reports `295 tests collected`

Interpretation:

- installation is far enough along to validate runtime services and targeted tests
- clean full collect baseline has been restored; the next testing task is a real full-suite run inside `.venv`

## 2. Phase 6 Test Expansion

Telegram text interaction adds new required test areas:

- Telegram authorization guard
- session load/save behavior
- assistant tool-routing correctness
- insufficient-evidence conversational response path
- sync-trigger behavior from chat

## 3. Phase 7 Test Expansion

Voice support adds:

- media metadata persistence
- download/transcription orchestration
- transcription error handling
- duplicate-job handling
- media cleanup

## 4. Recommended Test Layers

### Unit

- bot auth guard
- assistant routing logic
- tool schema and policy checks
- session-state helpers
- media-retention calculations

### Integration

- bot runtime against fake Telegram updates
- assistant calls into real service layer with test DB
- voice job orchestration with provider test doubles

### End-to-End

- authorized user asks text question and receives grounded answer
- authorized user sends voice note and receives transcript-based answer
- unauthorized user is blocked

## 5. Risk-Based Priorities

Highest-priority new tests:

- chat cannot bypass mutation policy
- assistant does not fabricate when search returns weak evidence
- session state survives restart
- voice jobs do not leak media files indefinitely

## 6. Current Testing Stop Point

The project is currently stopped at this practical boundary:

- local DB/Redis/app health checks have been validated
- targeted config and Google Docs client tests pass
- full-suite collection is green at the collect stage
- live Google Docs fetch with a real `GOOGLE_DOC_ID` still needs to be validated after credentials are finalized

If the next pass reveals only isolated defects, treat them as a maintenance/fix queue rather than inventing a new product phase.

## 7. CI Implication

If the Telegram runtime is added, CI should evolve to cover:

- assistant-related unit tests
- Telegram integration tests
- voice pipeline tests that use mocks/fakes rather than real external media services

Active implementation sequencing for these tests:

- [docs/tasks_phase6.md](tasks_phase6.md)

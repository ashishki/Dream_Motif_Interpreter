# ADR-007: Compose-First Deployment Documentation for the Telegram-Enabled Stack

Date: 2026-04-14  
Status: Proposed

## Context

Phase 6+ adds more than one long-running process: API, workers, and Telegram bot.
The project needs one canonical deployment story for the private single-user stack.

## Decision

Use Compose-first documentation as the canonical deployment shape for the Telegram-enabled system.
Document systemd as an optional private-VPS operating mode rather than the primary architecture story.

## Consequences

- clearer topology documentation
- easier mental model for the multi-service stack
- still compatible with private VPS operators who prefer systemd

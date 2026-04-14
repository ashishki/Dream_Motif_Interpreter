# ADR-006: Persist Bot Session State Durably

Date: 2026-04-14  
Status: Proposed

## Context

The current backend has no conversational session model.
The planned Telegram assistant needs restart-safe continuity and pending-action tracking.

## Decision

Persist bot session state durably in the core database layer.
Use Redis only for ephemeral coordination, locks, and job-state concerns.

## Consequences

- better restart behavior
- stronger auditability of assistant flow state
- more schema work than an in-memory-only approach, but lower operational fragility

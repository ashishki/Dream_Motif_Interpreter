# ADR-003: Telegram Adapter Lives Inside the Core Repository

Date: 2026-04-14  
Status: Proposed

## Context

Dream Motif Interpreter is extending from a backend-first system into a Telegram-enabled assistant.
The main architectural question is whether the Telegram interface should live in a separate repository/service or inside the current repository.

## Decision

Place the Telegram adapter inside the Dream Motif Interpreter repository as a separate internal application module and runtime process.

## Consequences

- domain logic remains close to the core product
- deployment topology grows, but repository drift risk is reduced
- the bot remains an interface adapter rather than a separate product

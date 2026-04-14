# ADR-004: Telegram Assistant Uses a Bounded Internal Tool Facade

Date: 2026-04-14  
Status: Proposed

## Context

A conversational Telegram layer is planned, but the dream archive must preserve existing approval, rollback, and retrieval guarantees.

## Decision

The Telegram assistant may invoke Dream Motif Interpreter only through an explicit bounded internal tool or service facade.
It must not receive unrestricted ORM, database, or mutation access.

## Consequences

- safer conversational integration
- clearer testing surface
- mutation capabilities can be phased in deliberately

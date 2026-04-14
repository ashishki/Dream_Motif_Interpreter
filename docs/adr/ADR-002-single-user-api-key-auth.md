# ADR-002: Single-User API Key Authentication

Date: 2026-04-14
Status: Accepted

## Context

The project is a single-user archive with a small authenticated API surface. It needs a lightweight access-control mechanism for local and programmatic use without adding a larger identity system.

## Decision

The API uses a single-user authentication model with an `X-API-Key` header for programmatic access, alongside the documented session-based path in the architecture. The maintained implementation validates protected routes with an environment-provided shared secret, while `GET /health` and `GET /auth/callback` remain public by design.

## Consequences

Authentication stays simple to operate in a single-user deployment, but the model is intentionally limited and would require a new ADR before expanding to multi-user or more granular authorization semantics.

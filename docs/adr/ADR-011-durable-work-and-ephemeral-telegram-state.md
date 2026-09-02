# ADR-011: Durable work in PostgreSQL and ephemeral Telegram state in Redis

Date: 2026-08-30  
Status: Accepted

## Context

The original implementation contract limited Redis to job identifiers, statuses and tokens. The
Telegram UX now needs exact pending dream/note/interpretation payloads to survive an ordinary bot
restart, while capture and voice side effects need leases, attempts and delivery cursors that must
survive Redis loss.

Putting durable work only in an in-process task or Redis would allow acknowledged capture to be
lost. Putting every short confirmation in the archive database would incorrectly turn interaction
drafts into long-lived dream records.

## Decision

- PostgreSQL owns durable capture-stage jobs, voice events, leases, attempts, reply payloads and
  chunk cursors.
- Redis may store the minimum private Telegram workflow payload needed to resume a confirmation:
  displayed dream references, pending dream/note text and pending interpretation request.
- Every such Redis value has a bounded TTL, stays inside the private deployment, and is never
  logged, traced, exposed by diagnostics or copied into public fixtures.
- Redis keys contain only a fixed namespace, chat identifier and state kind; they never contain
  dream text.
- Loss of Redis cannot delete canonical archive data. Production/staging startup fails when Redis
  is unavailable because safe short-confirmation routing cannot be guaranteed.
- PostgreSQL workers use database uniqueness, leases and compare-and-set finalization. External
  effects additionally use provider/document-side idempotency receipts where available.

## Consequences

Telegram pending state is private operational data and must be protected like the archive even
though it expires. Operators may check Redis health and aggregate counts, but must not dump values
to logs or tickets. Database backups include durable job/reply state; Redis backups are optional and
must follow the same privacy controls if enabled.

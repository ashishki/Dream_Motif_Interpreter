# ADR-011: Product-managed archive is the private-beta source of truth

- Date: 2026-07-18
- Status: Accepted
- Scope: private-beta product and synchronization boundary

## Context

The implementation already persists dreams, notes, themes, chunks, write status, and bot sessions in PostgreSQL. Telegram capture commits a `DreamEntry` before attempting a Google Docs write. Google Docs ingestion then imports document content into the same archive.

The product language is not equally clear. Some documents call PostgreSQL the canonical system of record, while Telegram copy tells the user that “archive”, “database”, and “storage” mean Google Docs. The current Google integration is periodic import plus targeted writes. It has no durable two-sided version vector, field-level merge policy, tombstone protocol, or user-visible conflict workflow. Body edits can change `content_hash`; external deletion is not reconciled; graph-output “delete” controls do not delete source archive rows.

Calling this full bidirectional synchronization would therefore overstate the implemented guarantee and create unsafe expectations for highly sensitive data.

## Decision

1. PostgreSQL is the single source of truth for the private beta.
2. A new dream must be accepted into the managed archive before any indexing, LLM, or Google operation. Provider outages may reduce searchability or mirroring, but must not destroy the captured dream.
3. Google Docs is an optional external source and mirror:
   - existing documents can be selected and imported;
   - successful product writes can be mirrored to a selected document;
   - external changes can be detected and imported;
   - Google Docs is not a peer source of truth until a formal reconciliation model is implemented.
4. The product must use explicit state language:
   - `Сохранено` — committed to the managed archive;
   - `Синхронизировано` — the selected external mirror reflects the known archive state;
   - `Есть внешние изменения` — Drive reports a newer external version that has not been reconciled;
   - `Конфликт` — both the managed record and external representation changed from the last common version;
   - `Нужен доступ` — authorization was revoked or is insufficient;
   - `Ошибка синхронизации` — the archive is safe, but the external operation failed.
5. Until reconciliation exists:
   - unchanged body text may update mutable Google metadata such as title and date by stable internal dream identity/content match;
   - changed body text must not silently overwrite an independently changed managed dream;
   - external deletions must not delete managed data automatically;
   - a user must see and resolve ambiguous changes.
6. Google connection is optional during onboarding. The first dream can be captured without Google credentials or a document ID.
7. Multi-user hosting is a separate phase. Before a second user is admitted, every archive row, query, job, source credential, vector record, and audit record must be scoped by an account/workspace boundary.

## Alternatives considered

### A. Google Docs as mandatory source of truth

Rejected for the private-beta default. It adds consent and document-selection friction before first value, couples capture reliability to Google availability, and makes multi-user isolation and deletion semantics harder to explain.

### B. Product-managed archive as source of truth

Accepted. It matches the current database ownership, allows immediate Telegram capture, preserves data during provider outages, and gives the product a place to implement durable audit, conflict, export, and deletion rules.

### C. Symmetric bidirectional synchronization

Deferred. This remains a possible later capability, but only after introducing durable per-source revisions, last-common-version state, field-level conflict rules, tombstones, retry/idempotency keys, and a user-facing reconciliation queue.

## External change detection target

The target mechanism is Drive `changes.getStartPageToken` + `changes.list`, with `changes.watch` notifications as an accelerator and polling as the fallback. Notifications are hints; workers must still read the change feed and run idempotent reconciliation. Watch channels expire and must be renewed. A file metadata marker can remain a bounded fallback for the current single-document prototype, but is not the final multi-source contract.

Document selection should use Google OAuth consent and Google Picker rather than manual document IDs. Access should be requested incrementally and only when the user connects an external source.

## Consequences

Positive:

- capture remains available when embeddings, LLMs, Redis notifications, or Google are degraded;
- user-facing storage language becomes unambiguous;
- external integration failures become recoverable sync problems instead of data-loss events;
- the future multi-user boundary is explicit.

Negative:

- Google Docs can no longer be described as an equal editing surface without qualification;
- external body edits and deletes require a reconciliation queue before they can be fully supported;
- current Telegram copy, deployment docs, and Mini App information architecture require updates.

## Migration and rollback

This ADR does not migrate or delete data. It names the ownership already reflected by the implemented database model. The rollout is documentation and behavior-first:

1. preserve capture on provider failure;
2. expose managed-archive and external-sync state separately;
3. replace manual Google Doc ID setup with consent and Picker;
4. add durable source revisions and conflict records before enabling true two-sided editing.

Rollback is limited to reverting product language and feature rollout. Reclassifying Google Docs as the source of truth later would require a new ADR, a data migration plan, and a tested recovery path.

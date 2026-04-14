# ADR-001: Append-Only Annotation Versioning

Date: 2026-04-14
Status: Accepted

## Context

Dream theme and taxonomy edits are subjective and may need to be reviewed or rolled back later. The system also needs an auditable history of user-driven and system-driven mutations.

## Decision

`AnnotationVersion` is append-only. Every mutation to `DreamTheme` or `ThemeCategory` writes an `AnnotationVersion` snapshot before commit, and application code does not delete from or update `annotation_versions`.

## Consequences

Rollback remains possible without reconstructing prior state from logs, audit history stays durable, and mutation paths must pay the small cost of writing a version row before commit.

# ADR-012 — Visible selections, bounded research, optional workspace

Date: 2026-09-18. Status: implemented on codex/kolia-experience-v1, not deployed.

## Decision

The visible ordered selection, not an intermediate retrieval batch, is the
conversation's operational scope. It has a UUID and creation time; Redis may
retain reference metadata under ADR-011 for at most its operational window.
Rehydration preserves identity and age. It is not permanent research memory.

The Telegram adapter publishes a selection after successful response delivery.
Several searches accumulate candidates within a turn. The model's visible source
order is resolved conservatively; ambiguous ordinals get an explicit numbered
source list. Opening a source preserves the working selection. Removing a source
changes only this scope, never the archive.

Voice replies stage reference metadata separately in TTL-bound Redis, bound by a
hash to the exact durable reply. Once all Telegram chunks have a durable cursor,
the adapter may publish those references. A failed send, expired or mismatched
metadata never publishes them. Source text is not copied into this metadata.
Reference context remains best effort; durable archive/voice delivery guarantees
are unchanged. Message-specific mapping is best effort if recovery resumes after
all chunks were already sent; the working selection can still be restored within
its TTL. This is not a claim of exactly-once Telegram network delivery.

A read-only research service loads an explicit source set (up to 20 complete
texts, 80,000 characters), verifies IDs, bounds provider time and makes at most
two structured-response attempts. Every quote must occur contiguously in the
loaded source; one invalid citation discards its entire observation. Actual
coverage and failures are exposed. Quote validation is not proof of entailment,
psychological meaning or clinical usefulness. Human judgement remains necessary.

The general tool loop reserves a final read-only model call when its tool budget
is exhausted, and explicitly marks incomplete responses. No tool calls from that
finalization are executed.

The optional Mini App is a same-origin, authenticated archive reader/search and
human note workspace. It uses existing storage and durable note jobs, not a
second source of truth. New search/research queries use POST bodies, not URL
query strings containing private content. Errors do not reflect request bodies.
No browser localStorage/sessionStorage persists the archive. Downloaded review
files require an explicit privacy confirmation.

Human #codes remain ordinary notes. Choosing a suggested label pre-fills a form;
only a subsequent save writes it. Motif confirmation and human code application
are separate operations. Unclicked suggestions are not rejected.

## Alternatives not selected

A multi-tenant migration, model/provider rewrite, autonomous agents, a graph
store, indefinite conversation memory and silent truncation of whole-archive
analysis. They do not solve the immediate single-operator experience problem.

## Limits and subsequent work

No new source-text editor, full archive deletion, saved investigation library,
automatic weekly reports or exhaustive time-series research is claimed. Existing
Google Docs body conflicts still require operator resolution. Review pagination
uses offset ordering, so concurrent review changes may shift pages; refresh is
safe and global counts are separate from loaded rows. Live Redis, Telegram,
Google Docs and model quality require an approved canary and observed acceptance.

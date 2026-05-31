# Entropy Core Reference

Status: implemented local memory action receipt helper; Core runtime not adopted
Last updated: 2026-05-31

## Purpose

Dream Motif Interpreter is not a Gensyn-style system and should not adopt
distributed candidate search. It can still use Entropy-style receipts for
privacy-sensitive memory actions: dream import, motif confirmation, deletion,
export, and interpretation persistence.

## Entropy Core Use

Default level: receipt-compatible for memory graph actions.

Local artifacts:

- `dream_memory_action_receipt` implemented in `app/services/proof_receipts.py`
- `motif_confirmation_record`
- `interpretation_referee_verdict`
- `privacy_export_receipt`
- `deletion_receipt`

Example:

```yaml
type: motif_confirmation_record
source_project: dream-motif-interpreter
dream_id: dream-001
motif_id: motif-001
user_action: confirmed
evidence:
  - path: docs/example-memory-map.md
verifier:
  method: user_confirmation
  status: passed
entropy_core:
  use_level: receipt_compatible_candidate
  runtime_dependency: false
```

## Gensyn Boundary

Do not apply Gensyn swarm/training patterns here by default. If the product ever
uses multiple interpretation lenses, they must be framed as optional reflective
views and pass a human/user confirmation step. No diagnosis, no automated truth
claim, no model-training loop.

## Proof Layer Implementation

Implemented now:

- `build_node_memory_receipt(...)` records graph node actions with a
  deterministic checksum.
- `build_edge_memory_receipt(...)` records graph edge actions and links model
  suggestions to dream fragment refs when available.
- Edge suggestions without source fragments are marked `needs_review`.
- Motif confirmation now stores private-local node and `appears_in` edge
  receipts in the append-only `AnnotationVersion.snapshot` for the
  `motif_induction` mutation.
- `build_privacy_export_receipt(...)` records deterministic graph export
  checksums without storing dream text in the receipt.
- `build_deletion_receipt(...)` records dream, graph node, or graph edge
  deletion controls and marks receipts `needs_review` when the deletion control
  does not include the requested subject.
- `build_hide_receipt(...)` records dream, graph node, or graph edge hide
  controls and marks receipts `needs_review` when the hide control does not
  include the requested subject.
- `build_rejection_receipt(...)` records rejected AI-suggestion controls and
  links them to source dream fragment references.
- `GET /dream-memory/export` returns the deterministic graph export with a
  `privacy_export_receipt` and is protected by the existing API-key middleware.
- `POST /dream-memory/privacy/delete` returns a graph-output deletion control
  with a `deletion_receipt`, stores it in `dream_graph_privacy_controls`, and
  does not delete source archive rows.
- `POST /dream-memory/privacy/hide` returns a reversible graph-output hide
  control with a `privacy_control_receipt` and stores it in
  `dream_graph_privacy_controls`.
- `POST /dream-memory/privacy/reject` returns a rejected-AI-suggestion graph
  control with a `privacy_control_receipt` and stores source dream fragment
  references without storing dream text.
- `GET /dream-memory/export` applies persisted graph-output hide, deletion, and
  rejected-suggestion controls before returning normal graph output.
- `tests/unit/test_proof_receipts.py` covers node receipts, fragment-linked
  edge receipts, source-less edge review status, graph export receipts, and
  deletion receipts.
- `tests/unit/test_dream_memory_export_api.py` covers the authenticated export
  and graph-output deletion control surfaces, and verifies raw dream text,
  titles, and source document IDs are not included in the export payload.
- `tests/unit/test_dream_graph_privacy_control_model.py` covers the durable
  privacy-control ORM model and migration.
- `tests/unit/test_motifs_api.py` covers motif confirmation receipt wiring.

Next implementation tasks:

1. Extend receipt wiring to future durable graph node/edge persistence after the
   mini-app memory map workflow stabilizes.
2. Add a mini-app-facing read contract for privacy controls and filtered graph
   state before building production UI.
3. Keep receipts private-local; do not sync dream evidence into Entropy Core.

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
- `tests/unit/test_proof_receipts.py` covers node receipts, fragment-linked
  edge receipts, and source-less edge review status.
- `tests/unit/test_motifs_api.py` covers motif confirmation receipt wiring.

Next implementation tasks:

1. Extend receipt wiring to future durable graph node/edge persistence after the
   mini-app memory map workflow stabilizes.
2. Add privacy export/deletion receipts before exposing export or deletion
   controls in a Telegram mini app.
3. Keep receipts private-local; do not sync dream evidence into Entropy Core.

# Entropy Core Reference

Status: optional reference
Last updated: 2026-05-29

## Purpose

Dream Motif Interpreter is not a Gensyn-style system and should not adopt
distributed candidate search. It can still use Entropy-style receipts for
privacy-sensitive memory actions: dream import, motif confirmation, deletion,
export, and interpretation persistence.

## Entropy Core Use

Default level: reference-only now; receipt-compatible later if memory-map
artifacts need stronger verification.

Possible local artifacts:

- `dream_memory_action_receipt`
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

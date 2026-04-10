# Decision Log — Dream Motif Interpreter

Version: 1.0
Last updated: 2026-04-10

---

## Rules

- Keep entries short and link to the authoritative document or section.
- Record why a decision was made and what it replaced.
- Update this file when architecture, runtime, governance, or major implementation direction changes.
- Mark superseded decisions explicitly instead of deleting them.

---

## Decision Index

| ID | Date | Status | Decision | Why it matters | Canonical source | Supersedes |
|----|------|--------|----------|----------------|------------------|------------|
| D-001 | 2026-04-10 | Active | Workflow solution shape (not agent loop) | Determines that LLM is called at fixed pipeline steps, not in a dynamic decision loop; prevents agentic drift | `docs/ARCHITECTURE.md#solution-shape` | none |
| D-002 | 2026-04-10 | Active | T1 runtime (no shell mutation, DB-backed, managed workers) | Rules out T2/T3 behaviors; any expansion requires ADR | `docs/ARCHITECTURE.md#runtime-and-isolation-model` | none |
| D-003 | 2026-04-10 | Active | RAG = ON; Tool-Use, Agentic, Planning, Compliance = OFF | RAG required for hybrid retrieval + citations; other profiles not justified for this scope | `docs/ARCHITECTURE.md#capability-profiles` | none |
| D-004 | 2026-04-10 | Active | PostgreSQL 16 + pgvector for both relational storage and vector index | Single data store eliminates a separate vector DB; pgvector supports cosine similarity at expected corpus scale | `docs/ARCHITECTURE.md#tech-stack` | none |
| D-005 | 2026-04-10 | Active | Hybrid RRF retrieval (pgvector cosine + PostgreSQL FTS) | Metaphor-aware queries benefit from semantic search; literal keyword queries benefit from FTS; RRF fusion avoids precision-recall tradeoff of either alone | `docs/ARCHITECTURE.md#rag-architecture` | none |
| D-006 | 2026-04-10 | Active | claude-haiku-4-5 for extraction/ranking drafts; claude-sonnet-4-6 for grounding and explanation | Cost-sensitive; haiku is sufficient for structured classification; sonnet needed for reading comprehension and span location | `docs/ARCHITECTURE.md#inference-model-strategy` | none |
| D-007 | 2026-04-10 | Active | Annotation versioning: all DreamTheme and ThemeCategory mutations write AnnotationVersion snapshot before commit | Required for rollback and audit trail given personal archive value; dream interpretation is subjective and must support revision | `docs/IMPLEMENTATION_CONTRACT.md#annotation-versioning` | none |
| D-008 | 2026-04-10 | Active | Human approval required for all taxonomy category promotion, rename, merge, delete | Dream interpretation is subjective; silent taxonomy mutation corrupts archive meaning; user must control what categories mean | `docs/ARCHITECTURE.md#human-approval-boundaries` | none |
| D-009 | 2026-04-10 | Active | ARQ (async Redis queue) for background workers, not Celery | Lighter-weight for single-user tool; native async compatibility with FastAPI/asyncpg; Celery overhead unjustified at this scale | `docs/ARCHITECTURE.md#tech-stack` | none |
| D-010 | 2026-04-10 | Active | Index schema versioned as v1; schema change requires ADR + full re-index | Ensures retrieval consistency; mixed-schema index is forbidden | `docs/ARCHITECTURE.md#index-strategy` | none |

---

## Retrieval Notes

- Read this file before revisiting architecture, changing runtime tier, resolving repeated findings, or overriding a prior tradeoff.
- If a task has `Context-Refs`, prefer those entries over scanning this file top-to-bottom.

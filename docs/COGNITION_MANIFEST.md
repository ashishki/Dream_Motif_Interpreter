# Cognition Manifest - Dream Motif Interpreter

---
artifact_kind: retrieval_manifest
project: dream-motif-interpreter
source_repo: Dream_Motif_Interpreter
status: active
canonical: false
generated: false
tags: [private-assistant, rag, adr-lineage, cognition]
---

Version: 1.0
Last updated: 2026-05-25

## Purpose

Repo-local engineering cognition map for a private single-user dream archive system. This manifest separates engineering memory from the product's personal/domain memory.

## Authority Rules

- Canonical repo artifacts win over this manifest.
- Personal dream content and assistant feedback are product data, not cross-project engineering memory.
- Obsidian and generated indexes are optional navigation layers.

## Project Identity

| Field | Value |
|-------|-------|
| Primary shape | Private single-user RAG assistant with bounded tools and background workers |
| Governance level | Standard/Strict for private data and write paths |
| Runtime tier | T1 |
| Active profiles | RAG, Tool-Use/bounded assistant, research augmentation |

## Canonical Truth

| Surface | Path | Notes |
|---------|------|-------|
| Architecture | `docs/ARCHITECTURE.md` | System boundaries |
| Contract | `docs/IMPLEMENTATION_CONTRACT.md` | Implementation rules |
| Task graph | `docs/tasks.md`, `docs/tasks_phase*.md` | Execution history |
| Session state | `docs/CODEX_PROMPT.md` | Current status |
| Decisions | `docs/DECISION_LOG.md`, `docs/adr/` | Rich ADR lineage |
| Journal | `docs/IMPLEMENTATION_JOURNAL.md` | Handoff continuity |
| Evidence | `docs/EVIDENCE_INDEX.md` | Proof lookup |
| Retrieval eval | `docs/retrieval_eval.md`, `scripts/eval.py` | RAG quality |
| Runbooks | `docs/RUNBOOK_TELEGRAM_BOT.md`, `docs/RUNBOOK_VOICE_PIPELINE.md`, `docs/SYSTEMD_SETUP.md` | Operations |
| Audits | `docs/audit/`, `docs/archive/` | Review history |

## Retrieval Scopes

| Scope | Start here | Include next |
|-------|------------|--------------|
| Retrieval change | `docs/retrieval_eval.md` | ADRs for source intake/parser profiles, evidence index |
| Assistant tool boundary | relevant ADR | assistant facade/tests, review reports |
| Google Docs write path | ADR/write release notes | tests, runbook, audit findings |
| Research augmentation | `docs/RESEARCH_AUGMENTATION.md`, ADR-009 | trust boundary tests and evals |
| Reviewer packet | task ACs and contract | relevant ADR, eval artifact, prior phase review |

## Known Gaps

| Gap | Impact | Migration step |
|-----|--------|----------------|
| Product memory and engineering cognition can be conflated | Cross-project graph could leak private/domain memory | Index engineering docs only; exclude raw dream content and product DB exports |
| Many phase task files exist | Retrieval can over-read old task plans | Prefer current tasks, ADRs, evals, and evidence rows over old phase task files |

## Generated Artifacts

| Artifact | Path | Policy |
|----------|------|--------|
| Cognition index | `generated/cognition/index.json` | Optional generated artifact; exclude product data |
| Context packets | `docs/context-packets/` | Commit only major review/regression packets |


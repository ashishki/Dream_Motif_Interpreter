# Project Brief Template

Use this document before running `prompts/STRATEGIST.md`. The goal is not to pre-design the system, but to give the Strategist enough context to choose the right solution shape, governance level, runtime tier, and model strategy without guessing.

Write short, concrete answers. If something is unknown, say `unknown` rather than inventing detail.

---

## 1. Project

- **Project name:**
- **One-sentence summary:**
- **Why this project exists:**
- **What success looks like in v1:**

## 2. Users and Workflows

- **Primary users / operators:**
- **Main workflow 1:**
- **Main workflow 2:**
- **Main workflow 3:**

## 3. Scope

- **In scope for v1:**
- **Out of scope / non-goals:**

## 4. AI Scope

- **Where AI may be needed:**
- **Where AI is explicitly not wanted:**
- **Possible retrieval / RAG need:**
- **Possible tool-use need:**
- **Possible planning / agentic behavior need:**

## 5. Deterministic Candidates

List the parts that probably should stay deterministic unless the Strategist proves otherwise.

- **Validation / policy checks:**
- **Routing / decision rules:**
- **Calculations / transformations:**
- **Retries / idempotency / audit triggers:**

## 6. Human Approval Boundaries

- **What actions must require human approval:**
- **What can be automated safely:**
- **Why these boundaries matter:**

## 7. Risk and Error Cost

- **What is expensive if the system is wrong:**
- **What is expensive if the system is slow:**
- **What is expensive if the system is inconsistent / variable:**
- **Blast radius if it fails badly:**
- **Audit / explainability needs:**

## 8. Data

- **Primary data sources:**
- **Approximate data volume:**
- **Does data change frequently:**
- **Sensitive / regulated data present:**
- **Retention / deletion expectations:**

## 8b. Continuity and Evidence

- **Which decisions are likely to be revisited later:**
- **What prior evidence or proof will future agents need to find quickly:**
- **Will work span multiple sessions / agents / weeks:**
- **Any existing docs, ADRs, audits, or notes that should become retrieval anchors:**

## 9. Integrations

- **External APIs / services:**
- **Databases / storage:**
- **Auth / identity provider:**
- **Webhooks / messaging / queues:**

## 10. Constraints

- **Preferred stack:**
- **Deployment target:**
- **Budget constraints:**
- **Latency / throughput expectations:**
- **Compliance requirements:**
- **Network / security restrictions:**

## 11. Runtime and Operations

- **Should runtime stay simple (managed service / container) if possible:**
- **Any need for shell, package, or toolchain mutation at runtime:**
- **Any need for privileged actions or long-lived isolated workers:**
- **Recovery / rollback expectations:**

## 12. Model and Cost Expectations

Only fill what you know. The Strategist should still make the final recommendation.

- **Cost sensitivity:** low / medium / high
- **Latency sensitivity:** low / medium / high
- **Expected request / task volume:**
- **If AI is used, should the system prefer smaller / cheaper models by default:**
- **Any required capabilities:** reasoning / multimodal / function calling / long context / structured output

## 13. Success Metrics

- **Business success metric:**
- **Quality metric:**
- **Latency metric:**
- **Cost metric:**
- **Operational metric:**

---

## Usage

1. Copy this template into your project notes or fill it inline in chat.
2. Send the completed brief to the Strategist.
3. Let the Strategist ask one batch of clarifying questions.
4. Use the resulting architecture package as the Phase 1 input to the rest of the playbook.

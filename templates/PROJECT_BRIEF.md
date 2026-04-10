Project Brief Template

Use this document before running prompts/STRATEGIST.md.

The goal is not to pre-design the system, but to give the Strategist enough context to choose the right solution shape, governance level, runtime tier, and model strategy without guessing.

Write short, concrete answers. If something is unknown, say unknown rather than inventing detail.

1. Project
Project name: Dream Motif Interpreter
One-sentence summary: An AI-assisted analysis tool for a personal dream journal that ingests long-form dream entries from Google Docs, assigns structured thematic categories to each dream, ranks those themes by salience, links themes to specific text fragments, detects recurring symbolic patterns across the archive, and supports thematic retrieval including metaphorical matches.
Why this project exists: The user has a large archive of dream notes stored in a multi-page Google Doc. Manual review is too slow and unreliable at scale. Standard chat-based analysis produces useful interpretations but lacks exhaustiveness, persistence, explainability, and structured reuse across the archive.
What success looks like in v1: The system can ingest the archive, segment it into dream entries, assign multiple themes to each dream, rank them by importance, link each theme to specific fragments of the dream, persist results, and allow browsing, search, and simple correlation analysis across the archive.
2. Users and Workflows
Primary users / operators: Primary user is the dream journal owner. Secondary role is the same user acting as curator of themes and interpretations.
Main workflow 1: Import or sync dream entries from Google Docs, segment them into individual records, extract metadata, and store them in a structured archive.
Main workflow 2: For each dream, generate a thematic profile: multi-label themes, ranked by salience, with linked text fragments that justify each theme.
Main workflow 3: Query the archive by theme or conceptual query (e.g., “mother”, “separation”, “contact with unconscious via tools”), including metaphorical matches.
Main workflow 4: Explore archive-level insights: recurring motifs, dominant themes, co-occurrence patterns, and suggested emergent categories.
Main workflow 5: Review and curate themes, approve new categories, refine interpretations, and maintain a stable thematic structure over time.
3. Scope
In scope for v1: Google Docs ingestion; dream segmentation; metadata extraction; per-dream multi-label theme tagging; theme salience ranking; fragment-level thematic grounding (linking themes to text spans); semantic and metaphor-aware retrieval; archive-wide recurrence detection; persistent thematic memory; explainable outputs; user curation; simple co-occurrence/correlation analysis.
Out of scope / non-goals: Clinical or psychiatric diagnosis; authoritative interpretation of dreams; therapeutic guidance; claims of objective symbolic meaning; social features; multi-user collaboration; multimodal analysis.
4. AI Scope
Where AI may be needed: Narrative interpretation; theme extraction; theme ranking; fragment-to-theme mapping; symbolic abstraction; metaphor-aware retrieval; clustering; archive summarization; explanation generation.
Where AI is explicitly not wanted: Deterministic storage, access control, sync logic, deletion logic, identity management, irreversible taxonomy changes without approval.
Possible retrieval / RAG need: Yes. Hybrid retrieval over dream entries and annotations using lexical + embedding-based search.
Possible tool-use need: Yes. Google Docs API, storage/database, indexing, retrieval, taxonomy management.
Possible planning / agentic behavior need: Limited. Bounded workflows only.
Interpretation Model: Hybrid. LLM-based semantic interpretation constrained by a structured theme framework and optionally supported by external conceptual knowledge (e.g., symbolic, psychological, or narrative interpretation patterns). The system may use these as heuristics but must not present interpretations as objective truth. Outputs are suggestive, evidence-backed, and explicitly framed as interpretations.
Pattern Detection Logic:
Patterns are detected:
within a single dream (theme composition and structure)
across the archive (recurrence, co-occurrence, evolution over time)
Methods include multi-label classification, embeddings, clustering, and co-occurrence analysis.
A pattern is defined as repeated appearance of semantically related themes, symbolic roles, or narrative structures—not just keywords.
Categorization Strategy:
Semi-structured taxonomy.
Initial categories can be predefined (e.g., “mother”, “separation”, “inner child”)
New categories emerge from data as suggestions
Multi-label assignment is allowed
Each theme has a salience score per dream
Categories require user approval to become stable
Overlap and ambiguity are expected and supported
5. Deterministic Candidates
Validation / policy checks: Access, sync validation, deduplication, deletion rules, taxonomy mutation constraints, confidence thresholds.
Routing / decision rules: Pipeline selection (ingest vs query), retrieval strategy selection, when to show tentative themes, approval triggers.
Calculations / transformations: Date parsing, segmentation, salience normalization, co-occurrence counts, correlation metrics, ranking formulas.
Retries / idempotency / audit triggers: Re-sync, re-indexing, annotation versioning, taxonomy logs, rollback mechanisms.
6. Human Approval Boundaries
Must require approval: Creating or promoting categories; merging/renaming/deleting themes; bulk relabeling; changing interpretation logic; exporting conclusions framed as meaning.
Can be automated: Ingestion, segmentation, draft theme assignment, ranking, fragment linking, retrieval, summaries, suggested correlations.
Why it matters: Dream interpretation is subjective. The system must assist without silently redefining meaning. Trust requires transparency and control.
7. Risk and Error Cost
High-cost errors: Incorrect themes, wrong salience ranking, incorrect fragment grounding, false metaphor matches, misleading correlations.
Latency cost: Slow ingestion or search reduces usability.
Consistency risk: Unstable labels or rankings across runs reduce trust.
Blast radius: Archive becomes misleading or unusable for reflection.
Explainability needs: Very high. Each theme must include:
supporting text fragments
explanation of mapping
confidence or strength
type of match (literal, semantic, symbolic)
8. Data
Primary sources: Google Docs dream journal; user edits; saved annotations; taxonomy definitions.
Volume: Small to medium, long-context entries.
Change frequency: Incremental growth over time.
Sensitivity: High personal sensitivity.
Retention: User-controlled deletion, reprocessing, and full reset capability.
9. Integrations
APIs: Google Docs/Drive API; LLM provider; embedding service.
Storage: Relational DB + vector index.
Auth: Google OAuth or simple auth.
Infra: Background jobs for ingestion and indexing.
10. Constraints
Preferred stack: unknown
Deployment: Lightweight web app or internal tool.
Budget: Cost-aware (avoid full reprocessing per query).
Latency: Fast interactive queries, async heavy tasks.
Compliance: Privacy-first.
Security: Minimal, scoped access to user data.
11. Runtime and Operations
Runtime simplicity: Yes.
Toolchain mutation: No.
Workers: Yes, for ingestion and indexing.
Recovery: Re-ingestion, annotation versioning, rollback.
12. Model and Cost Expectations
Cost sensitivity: medium
Latency sensitivity: medium
Volume: Low interactive, higher batch processing
Model strategy:
cheaper models for tagging, ranking drafts
stronger models for complex interpretation
Capabilities needed: reasoning, structured outputs, embeddings, semantic abstraction, ranking, explanation
13. Success Metrics
Business metric: Archive becomes a usable analytical tool.
Quality metric: Accurate theme tagging, meaningful ranking, correct fragment grounding, useful retrieval.
Latency metric: Responsive search, acceptable background processing time.
Cost metric: Controlled per-query cost via indexing and reuse.
Operational metric: Stable annotation memory, reliable sync, consistent outputs.
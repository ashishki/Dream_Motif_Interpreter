# Kolia Experience V1 — implementation handoff

Updated: 2026-09-18. Branch: `codex/kolia-experience-v1`.
Baseline: `1d8b61151556b02a4ad34a60a9b2919f14adad57`.
No direct main changes, production rollout, live provider mutation or real-data
inspection is part of this work. Never merge without explicit approval.

## Goal and actual delivery

Make Nikolai's existing single-operator workflow natural without making him
operate sync/retrieval internals or adding a multi-user platform. See
`docs/KOLIA_EXPERIENCE_V1.md` for the bounded delivered scope and ADR-012 for
selection/evidence/voice contracts.

Implemented: visible selection identity/order, safe ordinal continuation,
read-only remove/keep, preserved selection when opening a source, post-delivery
publication including voice, two-hour Redis context, bounded final answers,
source-verified structured research, explicit ordinary human #codes, a same-origin
archive reader/search/period/note workspace, selected research/text export,
complete review pagination and global counts. No new database migration or
production dependency was introduced.

## Commit slices

Published implementation commits (draft PR #7):
- `81d967e6b8b856e671c7b2bf26c314e331eda1db`: conversational selections,
  bounded answers, grounded research and delivered voice context.
- `0f989b440da87a74d06e6d619a10191f7f005955`: archive-first workspace and
  complete human review queue.
- `629f848e2cc5ef4bdb9e481d39b54aeb6a147f77`: user journeys and release gates.
- `4a69e21deeacbc310243785a20d5169397187b37`: cleaned, hash-verified product
  tree; all temporary transport files/workflows removed.
- `c1e899e09dc3ebc2efdf3282112c59b408f79b05`: align the existing public shell
  test with archive-first navigation and server-filtered pagination. Auth,
  no-store and CSP assertions remain intact.

The published tree at `4a69e21` was verified byte-for-byte against the locally
verified tree `41577720ddd0c55f7d2e275cf11c98db9d579f4c`. The later shell-test
fix was also verified by its exact content blob SHA. No CI security guard was
relaxed. Use remote commit IDs above, not earlier offline implementation IDs.

## Verification

Completed locally on Python 3.13.5 using the repository's hash-locked wheels:
- 913 tests passed: the entire local unit suite plus 16 real PTB routing replay
  tests (synthetic adapters; not a live bot).
- Earlier 341 focused tests passed: conversation/session/selection, research quote and
  budget contracts, voice publication, Telegram handlers, workspace HTTP auth,
  notes/search/period, motif pagination and PTB conversation routing replay.
- Ruff check/format, compileall, diff whitespace and inline JavaScript parsing.
- Offline Chromium/Playwright smoke: mobile and desktop; exact text/XSS;
  unknown note outcome retains input; explicit code save; partial research;
  stale search ignored; all 123 review fixtures reachable; global counts;
  keyboard close; no horizontal overflow. It uses synthetic API doubles and is
  **not** a live backend/Telegram browser test.

The first whole-unit local collection was blocked by the missing `cl100k_base`
tokenizer asset and disabled container network. This was resolved by retrieving
the official public tokenizer asset through a temporary branch-only CI artifact,
verifying its SHA-256 and rerunning the tests with the real tokenizer. No fake
tokenizer or production credentials were used. Public fixture: 8/8 cases, content
hash `e92f2925dbe1fa1af305cd1fea328575665b2f93711cab2a0863d168693dd841`.

GitHub Actions CI #296, run `35340039408`, passed for PR head
`c1e899e09dc3ebc2efdf3282112c59b408f79b05` (test merge
`d91e181bb2846e0a21a4b0220c50b6e35fc400d9` against the unchanged baseline).
- Full `pytest tests/`: **1029 passed, 6 skipped, 1 warning** in 71.85 seconds.
- Install/hash-lock verification, Ruff lint/format and container contract passed.
- Public fixture 8/8 and the configured retrieval evaluator passed.
- The warning is the existing SQLAlchemy schema-inspection warning for `vector`.
- PostgreSQL/pgvector and the production container were actually exercised in CI;
  model/Google/Telegram credentials were placeholders. The configured retrieval
  evaluator uses its stub path with placeholder keys, not live embedding quality.

This final handoff-only commit does not change product code or tests. Its own
CI result is available on draft PR #7; verify the latest head before deployment.
Run: https://github.com/ashishki/Dream_Motif_Interpreter/actions/runs/35340039408

Useful commands from the repository root:

```bash
uv run --locked --extra dev ruff check app scripts tests
uv run --locked --extra dev ruff format --check app scripts tests
uv run --locked --extra dev pytest -q tests/unit tests/integration/test_telegram_conversation_replay.py
python scripts/smoke_kolia_workspace.py --browser /usr/bin/chromium --output /tmp/kolia-smoke
```

The browser script requires a separate developer environment with Playwright and
an installed Chromium. It is not a production dependency. It uses `set_content`
with synthetic API/Telegram doubles and aborts external requests; no browser
security policy needs to be disabled. CI separately parses JavaScript with Node.

## Configuration and rollout

Existing single allowed Telegram chat and verified Mini App auth remain required.
Set `TELEGRAM_MINI_APP_URL` to the deployed `/dream-memory/mini-app` shell; no API
key is pasted into the browser. `ASSISTANT_RESEARCH_MODEL` is optional and must be
an available Anthropic model ID; blank inherits the assistant model. No provider
switch is implemented. External mythological research remains independently
feature-gated and is not necessary for the new archive research.

Follow the existing systemd rollout/runbook with backup + restore verification,
exact build SHA, readiness and writer quiescing. Do not start Compose alongside
active systemd writers. No deployment was run from this development session.

## Remaining acceptance, not completed claims

Run the approved disposable Google Docs/Telegram/Redis/provider canary and check
Mini App inside real mobile Telegram. Then follow
`docs/KOLIA_EXPERIENCE_ACCEPTANCE_RU.md` with Nikolai. Model usefulness and clinical
appropriateness cannot be inferred from synthetic code tests. Exact quote
validation does not prove the inference made from that quote.

Full source editing/deletion, conflict-resolution UI, indefinite named
investigations, automatic period reports, exhaustive longitudinal analysis and
multi-therapist isolation are not implemented by this release. Existing source
body conflicts remain fail-closed and require operator resolution. Context is
operational TTL state, not permanent memory; loss/expiry must not be guessed.

## Next action for an authorized reviewer

```bash
git fetch origin
# First inspect any local changes; do not reset another agent's work.
git status --short
git switch codex/kolia-experience-v1
git pull --ff-only origin codex/kolia-experience-v1
git log -8 --oneline
```

Read this handoff, check final CI and review the implemented changes. Do not
reimplement the slices above or execute the historical PR #5 branch command.
Deployment and observed acceptance require a separate explicit decision.

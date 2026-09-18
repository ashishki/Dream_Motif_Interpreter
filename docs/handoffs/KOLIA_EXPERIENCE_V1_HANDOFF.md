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

Local verified implementation commits before connector publication:
- `dc3e2d0`: visible selection and bounded Telegram conversation.
- `0ec519a`: verified research and voice selection continuity.
- `47cb329`: archive-first workspace and complete human review queue.

Publication may preserve patches under different commit IDs because transport
commits are separate parents. Verify the final branch tree and CI, not old local
IDs. Temporary source/dependency/patch transport workflows must be absent in the
final reviewed tree; the existing CI security guard is not relaxed for them.

## Verification

Completed locally on Python 3.13.5 using the repository's hash-locked wheels:
- 341 focused tests passed: conversation/session/selection, research quote and
  budget contracts, voice publication, Telegram handlers, workspace HTTP auth,
  notes/search/period, motif pagination and PTB conversation routing replay.
- Ruff check/format, compileall, diff whitespace and inline JavaScript parsing.
- Offline Chromium/Playwright smoke: mobile and desktop; exact text/XSS;
  unknown note outcome retains input; explicit code save; partial research;
  stale search ignored; all 123 review fixtures reachable; global counts;
  keyboard close; no horizontal overflow. It uses synthetic API doubles and is
  **not** a live backend/Telegram browser test.

The first whole-unit local collection was blocked by the missing `cl100k_base`
tokenizer asset and disabled container network. Do not replace the tokenizer
with a fake to turn this gate green. Full database/container checks belong to
GitHub CI; record their actual run and conclusion after publication.

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

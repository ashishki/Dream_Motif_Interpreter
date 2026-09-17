# Auth and Security

Last updated: 2026-08-31

## 1. Access model

Dream Motif Interpreter is a private, single-operator system.

- Protected HTTP routes accept a constant-time checked `X-API-Key` or verified Telegram Web App
  init data.
- Telegram long polling drops updates whose chat ID does not match
  `TELEGRAM_ALLOWED_CHAT_ID`; the guard runs before ordinary handlers.
- Public routes are limited to `/health`, `/auth/callback` and the static Mini App shell. The shell
  contains no dream data; its API calls still require authentication.
- `TELEGRAM_WEBAPP_AUTH_MAX_AGE_SECONDS` bounds replay of signed init data.
- API and Mini App responses use `Cache-Control: no-store`; baseline response headers disable MIME
  sniffing, referrer disclosure and unused browser capabilities. The Mini App CSP permits only the
  same origin plus Telegram's bootstrap script.

The same configured identifier is checked as the Telegram chat ID for bot updates and as the
Telegram user ID in signed Mini App init data. This intentionally supports a private one-user
chat; group-chat deployment is outside the current trust model.

## 2. Secrets and deployment identity

- Provider/API/Telegram credentials come from environment variables.
- Google service-account JSON is a read-only secret-mounted file and is never copied into the
  image or repository.
- `.env`, live document IDs and runtime state are not committed.
- `SECRET_KEY` is nonblank and at least 32 diverse bytes outside tests; known placeholder markers
  are rejected at startup.
- `BUILD_SHA` is public deployment metadata returned by `/health`. Production deploys must set the
  exact commit and reject `unknown`/mismatch during rollout.

The destructive retrieval evaluator ignores `DATABASE_URL`. It accepts only an explicitly named
PostgreSQL `TEST_DATABASE_URL`, safe database-name suffix, test/eval environment and
`--confirm-reset`.

## 3. Private content boundaries

Dream text, chunks, titles, fragments, voice transcripts and pending confirmation text must not be
written to logs, spans, metric labels or client error details.

PostgreSQL contains canonical/private archive and durable operational state. Under ADR-011, Redis
may contain minimal pending Telegram workflow values with a bounded TTL. Redis keys contain only
namespace/chat/state identifiers. Never dump Redis values or include them in tickets, screenshots
or public fixtures.

Feedback capsules contain hashes/lengths, tool names, dream IDs, route/model and build SHA—not raw
request, response or dream text. An optional user feedback comment remains private database data.

## 4. Voice privacy and durability

- A voice event is unique on `(chat_id, telegram_message_id)` and is claimed with a database lease.
- The downloaded path is persisted before background-processing acknowledgement.
- Raw audio stays inside `VOICE_MEDIA_DIR`; cleanup refuses paths outside this root.
- Transient transcription failure may retain raw audio for at most the retry/retention window.
- Raw audio is removed after a reply is durably staged or terminal retention handling completes.
- Untracked old `.ogg` files inside the root are swept without following paths outside it.
- The operational transcript is protected as sensitive database content, is not archive
  truth and is purged after `VOICE_TRANSCRIPT_RETENTION_SECONDS` (default seven days).
- A reply is staged before Telegram delivery. Long replies are split below Telegram limits and the
  chunk cursor is persisted; periodic recovery retries `reply_pending` without resending completed
  chunks.

## 5. Google Docs and external providers

Google Docs is an external editable mirror/intake boundary. Database receipts and named-range
markers prevent duplicate appends. All Docs indices are UTF-16-based. Credentials and raw provider
errors must not be echoed to users.

Anthropic, OpenAI, Google and Telegram receive only the data necessary for the requested operation.
External research is disabled unless its feature flag and API key are configured; results remain
untrusted suggestions with source attribution.

## 6. Operational rules

- Production/staging bot startup fails when Redis restart safety is unavailable.
- Do not manually mark durable jobs successful or delete them to clear an alert.
- Do not use shell globs or paths outside `VOICE_MEDIA_DIR` for media cleanup.
- Rotate a Telegram/provider/API key immediately if it may have appeared in logs or source.
- Keep database, Redis and named volumes private; backups inherit the same content sensitivity.
- Green CI proves synthetic code contracts, not live provider permissions or absence of operator
  data in an external system. Run the private canary after deployment.

See [ADR-002](adr/ADR-002-single-user-api-key-auth.md),
[ADR-011](adr/ADR-011-durable-work-and-ephemeral-telegram-state.md),
[IMPLEMENTATION_CONTRACT.md](IMPLEMENTATION_CONTRACT.md) and
[RUNBOOK_VOICE_PIPELINE.md](RUNBOOK_VOICE_PIPELINE.md).

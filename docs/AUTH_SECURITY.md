# Auth and Security

Last updated: 2026-04-15 (P8-T01 — resolved pending security decisions)

## 1. Current Backend Auth

The backend currently uses single-user API-key authentication for protected HTTP routes.

Public exceptions are intentionally limited.

See:

- [ADR-002](adr/ADR-002-single-user-api-key-auth.md)
- [app/main.py](/home/ashishki/Documents/dev/ai-stack/projects/Dream_Motif_Interpreter/app/main.py)

## 2. Planned Telegram Auth Model

Telegram access should remain single-user and private.

Recommended controls:

- allowlisted Telegram `chat_id`
- allowlisted Telegram `user_id` where available

This is separate from HTTP API-key auth.

## 3. Authorization Policy for Phase 6

Recommended Phase 6 policy:

- allow read/query operations through chat
- allow explicit sync trigger through chat
- defer archive mutations through chat

Reason:

- lowers risk
- preserves audit clarity
- avoids conversational ambiguity in curation

## 4. Secret Handling

- API keys, bot tokens, and Google credentials must remain outside source control
- if a Google service-account JSON exists operationally, store it securely and do not commit it
- logs and traces must not emit secrets

## 5. Media and Transcript Security

For Phase 7 voice support:

- raw audio should be short-lived
- transcript retention must be explicit
- temporary media paths must be writable only to the service account running the app

## 6. Observability Constraints

- no dream raw text in logs
- no transcript text in logs unless explicitly redacted and justified
- use IDs and status codes for operational tracing

## 7. Resolved Security Decisions (Phase 7)

All items previously pending have been decided and implemented:

- **Telegram allowlist field**: `chat_id` only (`TELEGRAM_ALLOWED_CHAT_ID`). `user_id` allowlisting is deferred to a future phase.
- **Raw audio retention**: deleted **immediately** after successful transcription via `delete_local_voice_file`. A sweep cleanup (`cleanup_voice_media`) handles any survivors. Retention window is configurable via `VOICE_RETENTION_SECONDS` (default: 3600 seconds).
- **Transcript retention**: transcripts are not stored independently. They exist only transiently in memory during the `transcribe_and_reply` task and are immediately passed to `handle_chat`. No transcript is written to disk or DB.
- **Transcription provider**: **OpenAI Whisper API** (managed, remote). Local Whisper is deferred — no model management burden for Phase 7. See `app/workers/transcribe.py`.

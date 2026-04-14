# Auth and Security

Last updated: 2026-04-14

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

## 7. Pending Security Decisions

- final Telegram allowlist fields
- raw audio retention length
- transcript retention length
- whether transcription is remote or local

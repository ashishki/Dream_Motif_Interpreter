# Runbook — Telegram Bot

Last updated: 2026-04-15 (P6-T06 update)

## 1. Purpose

Operate the Telegram bot runtime for Dream Motif Interpreter (Phase 6+ implemented).

## 2. Primary Responsibilities

- accept authorized updates
- reject unauthorized updates
- route user text and voice requests
- call assistant tools safely
- report failures clearly

## 3. Startup Checklist

- `TELEGRAM_BOT_TOKEN` set in environment
- `TELEGRAM_ALLOWED_CHAT_ID` set to the single authorized chat ID
- `ANTHROPIC_API_KEY` set (required for the bounded tool-use loop)
- `DATABASE_URL` reachable and migrations applied (including 007_add_bot_sessions)
- `REDIS_URL` reachable

Startup command (direct):

```bash
python3 -m app.telegram
```

Startup via Compose:

```bash
docker compose up telegram-bot
```

The bot process runs long polling. No public webhook endpoint is required for Phase 6.

Optional tuning:

```env
ASSISTANT_MODEL=claude-haiku-4-5-20251001   # default; override for a different model tier
```

## 4. Common Failure Modes

### Bot starts but receives nothing

Check:

- bot token validity
- polling/webhook mode mismatch
- deployment firewall or connectivity

### Bot receives messages from unauthorized source

Check:

- chat ID configuration
- whether the bot was added to an unexpected chat

### Bot replies with backend failure

Check:

- DB connectivity
- Redis connectivity
- LLM credentials
- retrieval service health

## 5. Safety Rule

If chat-driven mutation tools are not in the approved phase scope, disable or omit them entirely.

## 6. Logging Rule

Use identifiers and statuses.
Do not log raw dream text or secrets.

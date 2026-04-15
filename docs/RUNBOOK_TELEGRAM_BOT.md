# Runbook — Telegram Bot

Last updated: 2026-04-15

## 1. Purpose

Operate the Telegram bot runtime for Dream Motif Interpreter once Phase 6+ is implemented.

## 2. Primary Responsibilities

- accept authorized updates
- reject unauthorized updates
- route user text and voice requests
- call assistant tools safely
- report failures clearly

## 3. Startup Checklist

- bot token present
- allowed chat ID configured
- Postgres reachable
- OpenAI, Anthropic, and Google Docs credentials configured if assistant-backed search or sync paths are used

Startup command:

```bash
python3 -m app.telegram.bot
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

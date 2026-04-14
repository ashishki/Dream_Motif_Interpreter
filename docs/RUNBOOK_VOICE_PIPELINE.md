# Runbook — Voice Pipeline

Last updated: 2026-04-14

## 1. Purpose

Operate and troubleshoot the voice-message path once Phase 7 is implemented.

## 2. Startup Checklist

- media directory exists and is writable
- transcription provider credentials or binaries are available
- background workers are running
- cleanup schedule is enabled

## 3. Common Failure Modes

### Voice download fails

Check:

- Telegram file access
- disk path permissions
- network connectivity

### Transcription job fails

Check:

- provider credentials
- model availability
- timeout thresholds
- worker health

### Media files accumulate

Check:

- cleanup schedule configuration
- media retention setting
- worker or cleanup process failure

## 4. Recovery Rules

- failed jobs should be visible by job ID
- retries must be bounded
- if raw media remains after repeated failure, clean it manually and record the incident

## 5. Logging Rule

Do not log transcript text or raw dream content in clear text unless explicitly redacted and operationally justified.

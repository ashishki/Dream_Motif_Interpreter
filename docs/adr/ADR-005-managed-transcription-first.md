# ADR-005: Managed Transcription First for Telegram Voice

Date: 2026-04-14  
Status: Proposed

## Context

Phase 7 is expected to add Telegram voice-message support.
The main early tradeoff is managed transcription versus local Whisper.

## Decision

Start with a managed transcription provider in the first implementation pass.

## Consequences

- lower operational complexity in the initial rollout
- easier packaging for a private VPS deployment
- local Whisper remains a later optimization or privacy-driven change

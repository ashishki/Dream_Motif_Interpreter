# Dream Memory Map Product Spec

Version: 1.0
Status: Phase 26 product spec
Task: WS-26.1
Last updated: 2026-05-29

## 1. Product Definition

Dream Memory Map is a private Telegram mini app for reflective dream
journaling and pattern memory. It turns the existing dream archive into a visual
map of dreams, motifs, people, places, emotions, events, and recurring patterns.

The product is not psychological diagnosis, therapy, medical advice, or a claim
that a motif has one authoritative meaning. AI output is treated as a suggestion
for reflection until the user confirms, rejects, hides, or edits it.

Obsidian is a visual and structural reference only: graph view, backlinks,
tags, note relationships, and a private-vault feeling. Obsidian is not a
runtime, storage, export, or synchronization dependency.

## 2. Product Principles

- Keep the archive private by default.
- Preserve dream text as the source of truth.
- Link every suggested pattern back to source dream evidence.
- Separate AI-suggested links from user-confirmed memory.
- Make rejection and deletion as available as confirmation.
- Use reflective language: "may connect", "appears with", "recurs near", and
  "suggested pattern".
- Avoid diagnostic language: no disorder labels, symptom inference, clinical
  claims, or hidden psychological conclusions.

## 3. Surface Split

### Telegram Bot

The bot stays the fastest private capture and conversational surface:

- text dream capture
- voice dream capture and transcription
- explicit sync trigger and sync status explanation
- archive search through conversation
- direct retrieval of recent or named dreams
- bounded assistant answers over the archive
- lightweight confirmation/rejection prompts for suggested motifs
- Google Docs source management and write retry flows
- short notifications when a mini app action changes archive state

The bot should not become the primary graph canvas. It can summarize graph
relationships in text, but dense browsing, layout, filters, and export controls
belong in the mini app.

### Telegram Mini App

The mini app is the visual memory workspace:

- dream entry with structured review
- motif graph browsing
- recurring motif pages with linked evidence
- timeline exploration
- search and filter experience
- privacy, export, deletion, and hidden-item controls
- review queues for AI-suggested nodes and edges

The mini app reads and writes through the existing backend boundary. It should
not introduce a separate source of truth or a separate motif memory model.

## 4. Core Screens

### Dream Entry

Purpose: capture or review a dream before it becomes part of the durable
archive.

Required elements:

- date and title fields
- dream text body
- optional people, places, emotions, and event notes as user-editable chips
- draft motif suggestions clearly labeled as AI suggestions
- save, discard, and save-to-archive controls
- write-to-Google-Doc status when relevant
- privacy note that dream content remains private to the configured archive

Behavior:

- A saved dream can be indexed into the graph after backend ingestion.
- AI-suggested motifs remain draft until user-confirmed.
- The screen must not imply that a motif explains the dream.

### Motif Graph

Purpose: provide an Obsidian-inspired graph of recurring dream memory without
making Obsidian a dependency.

Required elements:

- node types: Dream, Motif, Person, Place, Emotion, Event
- visual distinction between user-confirmed and AI-suggested nodes/edges
- filters for node type, date range, confirmation state, hidden state, and
  source confidence
- edge preview that shows why two nodes are connected
- open-node action for the recurring motif page or dream detail
- empty and low-evidence states that avoid overclaiming

Behavior:

- AI-suggested connections are shown as provisional.
- Graph edges must be explainable by linked dream fragments in later schema
  work.
- Layout should support dense browsing but remain readable on mobile.

### Recurring Motif Page

Purpose: show one motif as a memory object with linked dreams and evidence.

Required elements:

- motif name and status: suggested, confirmed, rejected, or hidden
- short reflective summary, if available, marked as AI-generated suggestion
- linked dreams with dates, titles, and fragment previews
- related people, places, emotions, and events
- co-occurring motifs and possible evolution over time
- confirm, reject, rename, hide, and unhide controls
- source evidence list for every AI-suggested relationship

Behavior:

- Rejecting an interpretation does not delete the source dream.
- Renaming a motif changes the user's label, not the original dream text.
- The page should support WS-26.2 graph schema review by making source fragments
  a first-class requirement, without defining storage tables here.

### Timeline

Purpose: browse dreams and motif recurrence over time.

Required elements:

- chronological dream list
- motif recurrence markers
- date-range filtering
- density view for periods with many dreams
- links from timeline entries to dream detail and motif pages
- hidden/deleted state indicators where applicable

Behavior:

- Timeline language should say a motif "appears" or "recurs"; it must not
  diagnose mood, personality, or pathology.
- Deleted items are removed from normal output. Hidden items stay private but
  can be restored from settings if retention policy allows.

### Search

Purpose: find dreams, motifs, entities, and graph relationships without forcing
the user through chat.

Required elements:

- search box for dream text, titles, motifs, people, places, emotions, events,
  and dates
- filters for exact text, semantic search, node type, confirmation state, and
  date range
- result grouping by dream, motif, and graph relationship
- evidence snippets from source dream fragments
- clear no-result and insufficient-evidence states

Behavior:

- Search result snippets may show dream evidence, but no logs, analytics labels,
  or telemetry should store dream content.
- Suggested interpretations must be labeled separately from archive evidence.

### Privacy and Export Settings

Purpose: give the user explicit control over what is stored, visible, exported,
or deleted.

Required elements:

- export dream graph data in a documented JSON or Markdown-friendly format
- export scope controls: all data, date range, selected dreams, selected motifs,
  confirmed-only graph, or include suggestions
- delete dream control with clear impact on graph output
- hide dream or motif from graph output without deleting source text
- reject AI-suggested motifs or edges without deleting the source dream
- delete or purge derived graph suggestions for a dream
- show current source surfaces: backend archive, Google Docs write target, bot,
  and mini app

Behavior:

- Export must distinguish source dream text, user-confirmed labels, and
  AI-suggested labels.
- Deletion must remove the dream from normal search, graph, and timeline output
  according to the future backend deletion policy.
- Hiding is reversible; deletion may not be.

## 5. Graph Memory Model For Future Tasks

WS-26.2 should define the storage contract. This spec only names the product
objects and UX expectations:

- Dream: source archive entry, date, title, body, and source reference.
- Motif: recurring image, object, theme, phrase, or abstraction.
- Person: named or described figure appearing in dreams.
- Place: named, remembered, or inferred setting.
- Emotion: user-labeled or suggested affective tone.
- Event: notable action or episode within a dream.

Expected relationship language:

- appears_in
- repeats_with
- contradicts
- evolves_from
- user_confirmed

Every AI-suggested relationship should be traceable to source dream fragments in
the future schema. User confirmation status must be represented separately from
the model suggestion that produced the relationship.

## 6. Implementation Readiness For WS-26.2 And WS-26.3

WS-26.2 can use this spec to produce the graph schema by formalizing node
types, edge types, evidence references, confirmation status, hidden state, and
export shape.

WS-26.3 can use this spec to prototype:

- a mobile-first graph view
- a motif page with linked dream fragments
- a dream entry flow with suggested motif review
- visual treatment for suggested vs confirmed graph relationships
- privacy/export settings as a real screen, not a later afterthought

No backend schema, frontend framework, or Obsidian dependency is introduced by
this spec.

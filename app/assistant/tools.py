from __future__ import annotations

import uuid
from typing import Any

from app.assistant.facade import AssistantFacade

_BASE_TOOLS: list[dict[str, Any]] = [
    {
        "name": "search_dreams",
        "description": (
            "Search the dream archive using a natural-language query. "
            "Returns archive-backed evidence chunks. Use when the user asks about "
            "dream content, recurring symbols, or anything that requires archive retrieval."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural-language search query.",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_dream",
        "description": (
            "Retrieve the full text and themes of a single dream entry by its UUID. "
            "Use when the user asks for details about a specific dream."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "dream_id": {
                    "type": "string",
                    "description": "UUID of the dream entry.",
                },
            },
            "required": ["dream_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_recent_dreams",
        "description": (
            "List the most recent dream entries from the archive, newest first. "
            "Use when the user asks what was recorded recently."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of entries to return (default 10, max 20).",
                },
            },
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_patterns",
        "description": (
            "Retrieve recurring theme patterns and co-occurrence patterns from the dream archive. "
            "Use when the user asks about patterns, recurring symbols, or theme frequencies."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_theme_history",
        "description": (
            "Retrieve the versioning history of themes for a specific dream entry. "
            "Use when the user asks how the themes of a dream have changed over time."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "dream_id": {
                    "type": "string",
                    "description": "UUID of the dream entry.",
                },
            },
            "required": ["dream_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "trigger_sync",
        "description": (
            "Trigger a sync job to re-import the dream journal from Google Docs. "
            "Use only when the user explicitly requests a sync or archive refresh."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "doc_id": {
                    "type": "string",
                    "description": "Google Docs document ID to sync.",
                },
            },
            "required": ["doc_id"],
            "additionalProperties": False,
        },
    },
]

_GET_DREAM_MOTIFS_TOOL: dict[str, Any] = {
    "name": "get_dream_motifs",
    "description": (
        "Retrieve the inducted abstract motifs for a specific dream entry. "
        "Returns computational abstraction suggestions with confidence levels and status. "
        "Use when the user asks about abstract patterns or motifs for a specific dream. "
        "These are model-derived suggestions, not curated findings."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "dream_id": {
                "type": "string",
                "description": "UUID of the dream entry.",
            },
        },
        "required": ["dream_id"],
        "additionalProperties": False,
    },
}


def build_tools(motif_induction_enabled: bool = False) -> list[dict[str, Any]]:
    """Return the tool catalog.

    When motif_induction_enabled is True, the get_dream_motifs tool is
    included. When False, it is absent from the catalog entirely.
    """
    tools = list(_BASE_TOOLS)
    if motif_induction_enabled:
        tools.append(_GET_DREAM_MOTIFS_TOOL)
    return tools


async def execute_tool(
    tool_name: str,
    tool_input: dict[str, Any],
    facade: AssistantFacade,
) -> str:
    if tool_name == "search_dreams":
        query = str(tool_input.get("query", "")).strip()
        if not query:
            return "No query provided."
        result = await facade.search_dreams(query)
        if result.insufficient_reason is not None:
            return f"Insufficient evidence: {result.insufficient_reason}"
        if not result.items:
            return "No matching archive entries found."
        lines = ["Search results:"]
        for item in result.items[:5]:
            date_label = item.date.isoformat() if item.date is not None else "unknown date"
            lines.append(f"- [{date_label}] (score={item.relevance_score:.2f}) {item.chunk_text[:200]}")
        return "\n".join(lines)

    if tool_name == "get_dream":
        raw_id = str(tool_input.get("dream_id", "")).strip()
        try:
            dream_id = uuid.UUID(raw_id)
        except ValueError:
            return f"Invalid dream_id: {raw_id!r}"
        detail = await facade.get_dream(dream_id)
        if detail is None:
            return f"Dream not found: {raw_id}"
        theme_names = ", ".join(t.category_name for t in detail.themes) or "none"
        return (
            f"Dream {detail.id}\n"
            f"Date: {detail.date or 'unknown'}\n"
            f"Title: {detail.title}\n"
            f"Words: {detail.word_count}\n"
            f"Themes: {theme_names}\n"
            f"Text: {detail.raw_text[:500]}"
        )

    if tool_name == "list_recent_dreams":
        raw_limit = tool_input.get("limit", 10)
        limit = max(1, min(20, int(raw_limit)))
        dreams = await facade.list_recent_dreams(limit=limit)
        if not dreams:
            return "No dream entries in the archive."
        lines = [f"Recent dreams ({len(dreams)}):"]
        for dream in dreams:
            lines.append(f"- {dream.id} | {dream.date or 'unknown'} | {dream.title} ({dream.word_count} words)")
        return "\n".join(lines)

    if tool_name == "get_patterns":
        summary = await facade.get_patterns()
        lines = []
        if summary.recurring:
            lines.append("Recurring themes:")
            for pattern in summary.recurring[:10]:
                lines.append(
                    f"  {pattern.name}: {pattern.count} dreams ({pattern.percentage_of_dreams:.1f}%)"
                )
        else:
            lines.append("No recurring theme patterns found.")
        if summary.co_occurrence:
            lines.append("Co-occurring theme pairs:")
            for pair in summary.co_occurrence[:5]:
                ids = ", ".join(str(c) for c in pair.category_ids)
                lines.append(f"  [{ids}]: {pair.count} dreams")
        return "\n".join(lines) if lines else "No pattern data available."

    if tool_name == "get_theme_history":
        raw_id = str(tool_input.get("dream_id", "")).strip()
        try:
            dream_id = uuid.UUID(raw_id)
        except ValueError:
            return f"Invalid dream_id: {raw_id!r}"
        history = await facade.get_theme_history(dream_id)
        if not history:
            return "No theme history found for this dream."
        lines = [f"Theme history ({len(history)} versions):"]
        for entry in history[:10]:
            lines.append(f"- {entry.created_at} | {entry.entity_type} {entry.entity_id}")
        return "\n".join(lines)

    if tool_name == "trigger_sync":
        doc_id = str(tool_input.get("doc_id", "")).strip()
        if not doc_id:
            return "doc_id is required to trigger a sync."
        ref = await facade.trigger_sync(doc_id)
        return f"Sync job queued: {ref.job_id} (doc_id={ref.doc_id}, status={ref.status})"

    if tool_name == "get_dream_motifs":
        raw_id = str(tool_input.get("dream_id", "")).strip()
        try:
            dream_id = uuid.UUID(raw_id)
        except ValueError:
            return f"Invalid dream_id: {raw_id!r}"
        motifs = await facade.get_dream_motifs(dream_id)
        if not motifs:
            return "No abstract motifs found for this dream."
        lines = [f"Abstract motif suggestions for dream {raw_id}:"]
        for motif in motifs:
            confidence_label = motif.confidence or "unknown"
            if motif.status == "draft":
                status_note = "(unconfirmed suggestion)"
            elif motif.status == "confirmed":
                status_note = "(confirmed by user)"
            else:
                status_note = f"({motif.status})"
            lines.append(
                f"- [{confidence_label} confidence] {motif.label} {status_note}"
            )
            if motif.rationale:
                lines.append(f"  Rationale: {motif.rationale}")
        return "\n".join(lines)

    return f"Unknown tool: {tool_name}"

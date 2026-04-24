from __future__ import annotations

from datetime import date
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
        "name": "search_dreams_exact",
        "description": (
            "Exact text/word search across all dream entries using full-text search. "
            "Use when the user searches for a specific word, phrase, or image name that "
            "appears verbatim in dream text (e.g. 'find all dreams mentioning church', "
            "'find dreams with the word X'). Returns up to 20 results without relevance threshold."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The word, phrase, or image name to search for in dream text.",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "create_dream",
        "description": (
            "Create a new dream entry in the archive from user-provided text. "
            "Use only when the user explicitly asks to save, record, or add a new dream. "
            "Never use for editing, rewriting, or mutating an existing dream."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "raw_text": {
                    "type": "string",
                    "description": "Full dream text to store as a new archive entry.",
                },
                "title": {
                    "type": "string",
                    "description": "Optional short title for the dream entry.",
                },
                "date": {
                    "type": "string",
                    "description": "Optional dream date in ISO format YYYY-MM-DD.",
                },
            },
            "required": ["raw_text"],
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
    {
        "name": "manage_archive_source",
        "description": (
            "Manage Google Docs connected as dream archive sources. "
            "Use action='list' to see all connected docs; action='add' with doc_id "
            "to add a new source; action='remove' with doc_id to remove a source; "
            "action='get' to see primary doc_id; action='set' with doc_id to replace primary."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["get", "set", "list", "add", "remove"],
                    "description": (
                        "Action to perform: 'get' returns current primary doc_id, "
                        "'set' replaces it, 'list' returns all connected docs, "
                        "'add' adds a source, 'remove' removes a non-primary source."
                    ),
                },
                "doc_id": {
                    "type": "string",
                    "description": "Google Doc ID. Required for actions: set, add, remove.",
                },
            },
            "required": ["action"],
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

_RESEARCH_MOTIF_PARALLELS_TOOL: dict[str, Any] = {
    "name": "research_motif_parallels",
    "description": (
        "Search external sources for mythology, folklore, and cultural parallels to a "
        "confirmed inducted motif. REQUIRES explicit user confirmation before calling."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "motif_id": {
                "type": "string",
                "description": "UUID of the confirmed inducted motif.",
            },
        },
        "required": ["motif_id"],
        "additionalProperties": False,
    },
}


def build_tools(
    motif_induction_enabled: bool = False,
    research_enabled: bool = False,
) -> list[dict[str, Any]]:
    """Return the tool catalog.

    When motif_induction_enabled is True, the get_dream_motifs tool is
    included. When research_enabled is True, the research_motif_parallels tool
    is included. Disabled tools are absent from the catalog entirely.
    """
    tools = list(_BASE_TOOLS)
    if motif_induction_enabled:
        tools.append(_GET_DREAM_MOTIFS_TOOL)
    if research_enabled:
        tools.append(_RESEARCH_MOTIF_PARALLELS_TOOL)
    return tools


async def execute_tool(
    tool_name: str,
    tool_input: dict[str, Any],
    facade: AssistantFacade,
    *,
    chat_id: int | None = None,
    request_text: str | None = None,
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
            title_str = item.title if item.title else "без названия"
            lines.append(f"- [{date_label}] {title_str} (score={item.relevance_score:.2f})")
            if item.quote:
                lines.append(f"  Quote: \"{item.quote}\"")
            else:
                lines.append(f"  {item.chunk_text[:200]}")
        return "\n".join(lines)

    if tool_name == "search_dreams_exact":
        query = str(tool_input.get("query", "")).strip()
        if not query:
            return "No query provided."
        items = await facade.search_dreams_exact(query)
        if not items:
            return f"No dreams found containing '{query}'."
        lines = [f"Exact search results for '{query}' ({len(items)} fragments):"]
        for item in items:
            date_label = item.date.isoformat() if item.date is not None else "unknown date"
            title_str = item.title if item.title else "без названия"
            lines.append(f"- [{date_label}] {title_str} (score={item.relevance_score:.2f})")
            if item.quote:
                lines.append(f"  Quote: \"{item.quote}\"")
            else:
                lines.append(f"  {item.chunk_text[:200]}")
        return "\n".join(lines)

    if tool_name == "create_dream":
        if not _is_explicit_create_request(request_text):
            return "Dream creation requires an explicit user request to save a new dream entry."
        raw_text = str(tool_input.get("raw_text", "")).strip()
        if not raw_text:
            return "raw_text is required to create a dream entry."
        title = str(tool_input.get("title", "")).strip() or None
        raw_date = str(tool_input.get("date", "")).strip()
        dream_date = None
        if raw_date:
            try:
                dream_date = date.fromisoformat(raw_date)
            except ValueError:
                return f"Invalid date: {raw_date!r}. Expected YYYY-MM-DD."

        created = await facade.create_dream(
            raw_text,
            title=title,
            dream_date=dream_date,
            chat_id=chat_id,
        )
        status = "saved" if created.created else "already existed"
        return (
            f"Dream {status}: {created.id} | {created.title} | "
            f"date={created.date or 'unknown'} | source={created.source_doc_id}"
        )

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
        raw_text_clean = detail.raw_text.replace("*", "").replace("<", "")
        return (
            f"Dream {detail.id}\n"
            f"Date: {detail.date or 'unknown'}\n"
            f"Title: {detail.title}\n"
            f"Words: {detail.word_count}\n"
            f"Themes: {theme_names}\n"
            f"Text: {raw_text_clean[:2000]}"
        )

    if tool_name == "list_recent_dreams":
        raw_limit = tool_input.get("limit", 10)
        limit = max(1, min(20, int(raw_limit)))
        dreams = await facade.list_recent_dreams(limit=limit)
        if not dreams:
            return "No dream entries in the archive."
        lines = [f"Recent dreams ({len(dreams)}):"]
        for dream in dreams:
            title_str = dream.title if dream.title else "без названия"
            date_str = dream.date or "unknown"
            themes_str = ", ".join(dream.theme_names) if dream.theme_names else "нет тем"
            preview = dream.raw_text_preview.strip()[:200] if dream.raw_text_preview else ""
            lines.append(f"- {date_str} | {title_str}")
            if preview:
                lines.append(f"  preview: {preview}")
            if dream.theme_names:
                lines.append(f"  themes: {themes_str}")
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
        refs = await facade.trigger_sync(doc_id)
        if len(refs) == 1:
            ref = refs[0]
            return f"Sync job queued: {ref.job_id} (doc_id={ref.doc_id}, status={ref.status})"
        lines = [f"Sync jobs queued ({len(refs)} sources):"]
        for ref in refs:
            lines.append(f"  - {ref.doc_id}: job_id={ref.job_id} ({ref.status})")
        return "\n".join(lines)

    if tool_name == "manage_archive_source":
        action = str(tool_input.get("action", "")).strip()
        if action == "get":
            current = facade.get_archive_source()
            return f"Current primary archive source: {current}"
        if action == "set":
            new_doc_id = str(tool_input.get("doc_id", "")).strip()
            if not new_doc_id:
                return "doc_id is required for action='set'."
            facade.set_archive_source(new_doc_id)
            return f"Primary archive source updated to: {new_doc_id} (takes effect on next sync)"
        if action == "list":
            sources = facade.list_archive_sources()
            if not sources:
                return "No archive sources configured."
            lines = ["Connected Google Docs:"]
            for i, source in enumerate(sources, 1):
                tag = " (primary)" if i == 1 else ""
                lines.append(f"{i}. {source}{tag}")
            return "\n".join(lines)
        if action == "add":
            new_doc_id = str(tool_input.get("doc_id", "")).strip()
            if not new_doc_id:
                return "doc_id is required for action='add'."
            updated = facade.add_archive_source(new_doc_id)
            lines = ["Archive source added. Updated list:"]
            for i, source in enumerate(updated, 1):
                tag = " (primary)" if i == 1 else ""
                lines.append(f"{i}. {source}{tag}")
            return "\n".join(lines)
        if action == "remove":
            doc_id_to_remove = str(tool_input.get("doc_id", "")).strip()
            if not doc_id_to_remove:
                return "doc_id is required for action='remove'."
            try:
                updated = facade.remove_archive_source(doc_id_to_remove)
            except ValueError as exc:
                return str(exc)
            lines = ["Archive source removed. Updated list:"]
            for i, source in enumerate(updated, 1):
                tag = " (primary)" if i == 1 else ""
                lines.append(f"{i}. {source}{tag}")
            return "\n".join(lines)
        return f"Unknown action: {action!r}. Use 'list', 'add', 'remove', 'get', or 'set'."

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
            lines.append(f"- [{confidence_label} confidence] {motif.label} {status_note} [id={motif.id}]")
            if motif.rationale:
                lines.append(f"  Rationale: {motif.rationale}")
        return "\n".join(lines)

    if tool_name == "research_motif_parallels":
        raw_id = str(tool_input.get("motif_id", "")).strip()
        try:
            motif_id = uuid.UUID(raw_id)
        except ValueError:
            return f"Invalid motif_id: {raw_id!r}"
        parallels = await facade.research_motif_parallels(
            motif_id,
            triggered_by="assistant",
        )
        if not parallels:
            return "No external parallels were returned for this motif."
        lines = ["External motif parallels (speculative, not verified):"]
        for parallel in parallels:
            overlap_degree = parallel.get("overlap_degree") or "uncertain"
            label = parallel.get("label") or "unlabeled parallel"
            domain = parallel.get("domain") or "unknown domain"
            source_url = parallel.get("source_url") or "no source URL"
            retrieved_at = parallel.get("retrieved_at") or "unknown retrieval time"
            lines.append(f"- [{overlap_degree}] {label} ({domain})")
            relevance_note = parallel.get("relevance_note")
            if relevance_note:
                lines.append(f"  Note: {relevance_note}")
            lines.append(f"  Source: {source_url} | Retrieved: {retrieved_at}")
        return "\n".join(lines)

    return f"Unknown tool: {tool_name}"


def _is_explicit_create_request(request_text: str | None) -> bool:
    if not request_text:
        return False

    text = request_text.casefold()
    phrases = (
        "save this dream",
        "record this dream",
        "add this dream",
        "create a new dream",
        "save a new dream",
        "add a new dream",
        "запиши сон",
        "записать сон",
        "сохрани сон",
        "сохранить сон",
        "добавь сон",
        "добавить сон",
        "новый сон",
        "сохрани этот сон",
        "запишите",
        "запиши это",
        "добавь в архив",
        "сохрани в архив",
        "сохранить в архив",
        "занести в архив",
        "занеси в архив",
    )
    return any(phrase in text for phrase in phrases)

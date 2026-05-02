from __future__ import annotations

from datetime import date
import re
import uuid
from typing import Any

from app.assistant.facade import AssistantFacade, SearchResultItem
from app.assistant.facade import _resolve_relative_dream_date
from app.retrieval.query import extract_concrete_image_query
from app.shared.config import extract_google_doc_id, get_doc_name

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
        "name": "search_dreams_by_title",
        "description": (
            "Search dream entries by title/name and return dream UUIDs for follow-up get_dream calls. "
            "Use this before content search when the user asks for a specific dream by title, name, "
            "or a phrase that appears to be the dream's heading. If multiple matches are returned, "
            "present them as options instead of guessing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Dream title or title fragment to search for.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of matching titles to return (default 10, max 20).",
                },
                "date": {
                    "type": "string",
                    "description": (
                        "Optional dream date used to disambiguate title matches. "
                        "Accepts YYYY-MM-DD, DD.MM.YY, DD.MM.YYYY, or Russian relative dates."
                    ),
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "add_dream_note",
        "description": (
            "Add a note to a dream entry. Use when the user says 'note: ...' or asks to "
            "add a note to a dream."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "note_text": {
                    "type": "string",
                    "description": "The note text to add.",
                },
                "dream_id": {
                    "type": "string",
                    "description": "UUID of the dream (optional; uses most recent if omitted).",
                },
            },
            "required": ["note_text"],
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
            "Omit doc_id to sync all configured sources. "
            "Use only when the user explicitly requests a sync or archive refresh."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "doc_id": {
                    "type": "string",
                    "description": "Optional Google Docs document ID to sync. Omit to sync all configured sources.",
                },
            },
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "retry_write_to_google_doc",
        "description": (
            "Retry writing a dream entry to Google Doc after a previous failure. "
            "Use when the user asks to retry, repeat, or re-save the write to Google Doc. "
            "Omit dream_id to retry for the most recently created dream."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "dream_id": {
                    "type": "string",
                    "description": "Optional UUID of the dream to write. Omit to use the most recently created dream.",
                },
            },
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "manage_archive_source",
        "description": (
            "Manage Google Docs connected as dream archive sources. "
            "action='find' with title searches Google Drive by document name — use this when "
            "the user mentions a document by name instead of URL/ID; if a unique match is found "
            "it is added and synced automatically. "
            "action='add' with doc_id adds a source and starts sync. "
            "action='list' lists all connected docs. "
            "action='get' returns the primary doc_id. "
            "action='set' replaces the primary. "
            "action='remove' removes a non-primary source. "
            "doc_id accepts a bare ID or a full Google Docs URL. "
            "action='create' creates a new document — the bot owns it so no sharing is needed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["get", "set", "list", "add", "remove", "find", "create"],
                    "description": (
                        "'create' creates a new Google Doc by title, adds it, starts sync; "
                        "'find' searches existing docs by title; "
                        "'add' adds by doc_id/URL and starts sync; "
                        "'list' returns all connected docs; "
                        "'get' returns primary doc_id; "
                        "'set' replaces primary; "
                        "'remove' removes a non-primary source."
                    ),
                },
                "doc_id": {
                    "type": "string",
                    "description": "Google Doc ID or URL. Required for: set, add, remove.",
                },
                "title": {
                    "type": "string",
                    "description": "Document name to search for. Required for action='find'.",
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
        exact_query = extract_concrete_image_query(query)
        exact_items: list[SearchResultItem] = []
        if exact_query is not None:
            exact_items = await facade.search_dreams_exact(exact_query)
        try:
            result = await facade.search_dreams(query)
        except Exception:
            if not exact_items:
                raise
            items = _merge_search_result_items(exact_items)
            lines = ["Search results:"]
            for item in items[:5]:
                lines.extend(_format_search_result_payload(item))
            return "\n".join(lines)
        if exact_items:
            semantic_items = [] if result.insufficient_reason is not None else result.items
            items = _merge_search_result_items([*exact_items, *semantic_items])
            lines = ["Search results:"]
            for item in items[:5]:
                lines.extend(_format_search_result_payload(item))
            return "\n".join(lines)
        if result.insufficient_reason is not None:
            if "verified archive-backed matches" in result.insufficient_reason:
                return "No more archive-backed matches found."
            return f"Insufficient evidence: {result.insufficient_reason}"
        if not result.items:
            return "No matching archive entries found."
        lines = ["Search results:"]
        for item in result.items[:5]:
            lines.extend(_format_search_result_payload(item))
        return "\n".join(lines)

    if tool_name == "search_dreams_exact":
        query = str(tool_input.get("query", "")).strip()
        if not query:
            return "No query provided."
        items = await facade.search_dreams_exact(query)
        if not items:
            # Fallback: exact word not found — try semantic search for the same query
            fallback = await facade.search_dreams(query)
            if fallback.insufficient_reason is not None or not fallback.items:
                return f"No dreams found containing '{query}'."
            lines = [
                f"Exact match for '{query}' not found. Semantic search results:",
            ]
            for item in fallback.items[:5]:
                lines.extend(_format_search_result_payload(item))
            return "\n".join(lines)
        lines = [f"Exact search results for '{query}' ({len(items)} fragments):"]
        for item in items:
            lines.extend(_format_search_result_payload(item))
        return "\n".join(lines)

    if tool_name == "search_dreams_by_title":
        query = str(tool_input.get("query", "")).strip()
        if not query:
            return "No title query provided."
        limit = _bounded_int(tool_input.get("limit", 10), default=10, minimum=1, maximum=20)
        raw_date = str(tool_input.get("date", "")).strip()
        dream_date = None
        if raw_date:
            try:
                dream_date = _parse_tool_date(raw_date)
            except ValueError:
                return (
                    f"Invalid date: {raw_date!r}. "
                    "Expected YYYY-MM-DD, DD.MM.YY, DD.MM.YYYY, or Russian relative date."
                )
        search_kwargs: dict[str, Any] = {"limit": limit}
        if dream_date is not None:
            search_kwargs["dream_date"] = dream_date
        items = await facade.search_dreams_by_title(query, **search_kwargs)
        if not items:
            fallback = await facade.search_dreams(query)
            if fallback.insufficient_reason is not None or not fallback.items:
                return f"No title match found for '{query}'. No matching archive entries found."
            lines = [f"No title match found for '{query}'. Content search results:"]
            for item in fallback.items[:5]:
                lines.extend(_format_search_result_payload(item))
            return "\n".join(lines)
        if len(items) == 1:
            detail = await facade.get_dream(items[0].dream_id)
            if detail is None:
                lines = [
                    f"Title search result for '{query}', but full dream retrieval failed:",
                ]
                lines.extend(_format_title_search_result_payload(items[0]))
                return "\n".join(lines)
            return "\n".join(
                [
                    f"Single title match found for '{query}'. Full dream:",
                    _format_dream_detail_payload(detail),
                ]
            )
        else:
            lines = [
                f"Title search results for '{query}' ({len(items)} matches).",
                "Present these as options; do not guess which one the user meant.",
            ]
        for item in items:
            lines.extend(_format_title_search_result_payload(item))
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
                dream_date = _resolve_relative_dream_date(raw_date) or date.fromisoformat(raw_date)
            except ValueError:
                return f"Invalid date: {raw_date!r}. Expected YYYY-MM-DD or Russian relative date."

        created = await facade.create_dream(
            raw_text,
            title=title,
            dream_date=dream_date,
            chat_id=chat_id,
        )
        if not created.created:
            return (
                f"Запись уже существует в архиве (id={created.id}, title={created.title!r}). "
                "В Google Doc повторно не записывается."
            )
        lines = [
            f"Dream saved: {created.id} | {created.title} | "
            f"date={created.date or 'unknown'} | source={created.source_doc_id}"
        ]
        if created.written_to_google_doc:
            lines.append("Запись добавлена в Google Doc.")
        else:
            lines.append(
                "Запись сохранена в архиве. "
                "Чтобы повторить запись в Google Doc, скажите «повтори запись в Google Doc»."
            )
        return "\n".join(lines)

    if tool_name == "add_dream_note":
        note_text = str(tool_input.get("note_text", "")).strip()
        if not note_text:
            return "note_text is required."
        raw_id = str(tool_input.get("dream_id", "")).strip()
        dream_id = None
        if raw_id:
            try:
                dream_id = uuid.UUID(raw_id)
            except ValueError:
                return f"Invalid dream_id: {raw_id!r}"
        success, message = await facade.add_dream_note(
            note_text,
            dream_id=dream_id,
            chat_id=chat_id,
        )
        return message

    if tool_name == "retry_write_to_google_doc":
        raw_id = str(tool_input.get("dream_id", "")).strip()
        dream_id = None
        if raw_id:
            try:
                dream_id = uuid.UUID(raw_id)
            except ValueError:
                return f"Invalid dream_id: {raw_id!r}"
        success, doc_name, reason = await facade.retry_write_to_google_doc(
            dream_id=dream_id,
            chat_id=chat_id,
        )
        if success:
            return "Запись добавлена в Google Doc."
        if reason == "nothing_to_retry":
            return "Нет неудачной записи в Google Doc для повтора."
        return (
            "Не удалось записать в Google Doc. "
            "Сон не был добавлен в документ; можно повторить попытку позже."
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
        return _format_dream_detail_payload(detail)

    if tool_name == "list_recent_dreams":
        limit = _bounded_int(tool_input.get("limit", 10), default=10, minimum=1, maximum=20)
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
            lines.append(f"  dream_id: {dream.id}")
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
        try:
            refs = await facade.trigger_sync(doc_id, chat_id=chat_id)
        except RuntimeError as exc:
            return f"Sync unavailable: {exc}"
        if len(refs) == 1:
            ref = refs[0]
            return f"Sync job queued: {ref.job_id} (doc_id={ref.doc_id}, status={ref.status})"
        lines = [f"Sync jobs queued ({len(refs)} sources):"]
        for ref in refs:
            lines.append(f"  - {ref.doc_id}: job_id={ref.job_id} ({ref.status})")
        return "\n".join(lines)

    if tool_name == "manage_archive_source":
        action = str(tool_input.get("action", "")).strip()
        if action == "create":
            title = str(tool_input.get("title", "")).strip()
            if not title:
                return "title is required for action='create'."
            try:
                doc = facade.create_archive_source_document(title)
            except Exception as exc:
                return f"Failed to create document: {exc}"
            doc_id = doc["id"]
            updated = facade.add_archive_source(doc_id, name=doc["name"])
            write_target_create = facade.get_archive_source()
            lines = [
                f"Created new Google Doc: {doc['name']}",
                f"URL: {doc['url']}",
                "Sync started. Connected sources:",
            ]
            for i, source in enumerate(updated, 1):
                tag = " ← куда пишем" if source == write_target_create else ""
                lines.append(f"{i}. {get_doc_name(source)} ({source}){tag}")
            try:
                refs = await facade.trigger_sync(doc_id, chat_id=chat_id)
                if refs:
                    lines.append(f"Sync job queued: {refs[0].job_id}")
            except RuntimeError:
                lines.append("Note: sync could not be started automatically.")
            return "\n".join(lines)
        if action == "find":
            title = str(tool_input.get("title", "")).strip()
            if not title:
                return "title is required for action='find'."
            try:
                matches = facade.search_archive_source_by_title(title)
            except Exception as exc:
                return (
                    f"Search failed: {exc}. "
                    "Make sure the document is shared with the service account."
                )
            if not matches:
                return (
                    f"No Google Docs found matching '{title}'. "
                    "Make sure the document is shared with the service account "
                    f"(dream-180@dream-493107.iam.gserviceaccount.com)."
                )
            if len(matches) == 1:
                doc_id = matches[0]["id"]
                doc_name = matches[0]["name"]
                updated = facade.add_archive_source(doc_id, name=doc_name)
                write_target_find = facade.get_archive_source()
                lines = [f"Found and added: {doc_name} (id={doc_id}). Sync started."]
                lines.append("Connected sources:")
                for i, source in enumerate(updated, 1):
                    tag = " ← куда пишем" if source == write_target_find else ""
                    lines.append(f"{i}. {get_doc_name(source)} ({source}){tag}")
                try:
                    refs = await facade.trigger_sync(doc_id, chat_id=chat_id)
                    if refs:
                        lines.append(f"Sync job queued: {refs[0].job_id}")
                except RuntimeError:
                    lines.append("Note: sync could not be started automatically.")
                return "\n".join(lines)
            lines = [f"Multiple documents found matching '{title}'. Please clarify:"]
            for i, m in enumerate(matches, 1):
                lines.append(f"{i}. {m['name']} (id={m['id']})")
            lines.append("Reply with the document name or ID to add it.")
            return "\n".join(lines)
        if action == "get":
            current = facade.get_archive_source()
            return f"Current primary archive source: {current}"
        if action == "set":
            raw = str(tool_input.get("doc_id", "")).strip()
            if not raw:
                return "doc_id is required for action='set'."
            new_doc_id = extract_google_doc_id(raw)
            facade.set_archive_source(new_doc_id)
            return f"Primary archive source updated to: {new_doc_id} (takes effect on next sync)"
        if action == "list":
            sources = facade.list_archive_sources()
            if not sources:
                return "No archive sources configured."
            write_target = facade.get_archive_source()
            lines = ["Connected Google Docs:"]
            for i, source in enumerate(sources, 1):
                name = get_doc_name(source)
                tag = " ← куда пишем" if source == write_target else ""
                lines.append(f"{i}. {name} ({source}){tag}")
            return "\n".join(lines)
        if action == "add":
            raw = str(tool_input.get("doc_id", "")).strip()
            if not raw:
                return "doc_id is required for action='add'."
            new_doc_id = extract_google_doc_id(raw)
            updated = facade.add_archive_source(new_doc_id)
            write_target_add = facade.get_archive_source()
            lines = ["Archive source added. Sync started. Updated list:"]
            for i, source in enumerate(updated, 1):
                tag = " ← куда пишем" if source == write_target_add else ""
                lines.append(f"{i}. {get_doc_name(source)} ({source}){tag}")
            try:
                refs = await facade.trigger_sync(new_doc_id, chat_id=chat_id)
                if refs:
                    lines.append(f"Sync job queued: {refs[0].job_id}")
            except RuntimeError:
                lines.append("Note: sync could not be started automatically.")
            return "\n".join(lines)
        if action == "remove":
            raw = str(tool_input.get("doc_id", "")).strip()
            if not raw:
                return "doc_id is required for action='remove'."
            doc_id_to_remove = extract_google_doc_id(raw)
            try:
                updated = facade.remove_archive_source(doc_id_to_remove)
            except ValueError as exc:
                return str(exc)
            write_target = facade.get_archive_source()
            lines = ["Archive source removed. Updated list:"]
            for i, source in enumerate(updated, 1):
                tag = " ← куда пишем" if source == write_target else ""
                lines.append(f"{i}. {get_doc_name(source)} ({source}){tag}")
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
            lines.append(
                f"- [{confidence_label} confidence] {motif.label} {status_note} [id={motif.id}]"
            )
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


def _search_strength_label(score: float) -> str:
    if score >= 0.7:
        return "strong"
    if score >= 0.4:
        return "moderate"
    return "weak"


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _parse_tool_date(raw_date: str) -> date:
    relative = _resolve_relative_dream_date(raw_date)
    if relative is not None:
        return relative
    try:
        return date.fromisoformat(raw_date)
    except ValueError:
        pass

    match = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{2}|\d{4})", raw_date.strip())
    if match is None:
        raise ValueError(raw_date)
    day = int(match.group(1))
    month = int(match.group(2))
    year_raw = match.group(3)
    year = int(year_raw)
    if len(year_raw) == 2:
        year += 2000
    return date(year, month, day)


def _format_search_result_payload(item: Any) -> list[str]:
    date_label = item.date.isoformat() if item.date is not None else "unknown date"
    title_str = item.title if item.title else "без названия"
    strength = _search_strength_label(item.relevance_score)
    evidence_text = _search_evidence_text(item)
    return [
        f"- result_id: {item.dream_id}",
        f"  date: {date_label}",
        f"  title: {title_str}",
        f"  strength: {strength}",
        f'  evidence_text: "{evidence_text}"',
    ]


def _merge_search_result_items(items: list[SearchResultItem]) -> list[SearchResultItem]:
    grouped: dict[uuid.UUID, SearchResultItem] = {}
    for item in items:
        existing = grouped.get(item.dream_id)
        if existing is None:
            grouped[item.dream_id] = item
            continue

        relevance_score = max(existing.relevance_score, item.relevance_score)
        chunk_text = _merge_evidence_texts(existing.chunk_text, item.chunk_text)
        matched_fragments = _dedupe_search_fragments(
            [*existing.matched_fragments, *item.matched_fragments]
        )
        grouped[item.dream_id] = SearchResultItem(
            dream_id=existing.dream_id,
            date=existing.date or item.date,
            title=existing.title or item.title,
            chunk_text=chunk_text,
            relevance_score=relevance_score,
            matched_fragments=matched_fragments,
            quote=existing.quote or item.quote,
        )

    return sorted(grouped.values(), key=lambda item: item.relevance_score, reverse=True)


def _merge_evidence_texts(existing: str, new: str) -> str:
    if not new or new == existing:
        return existing
    parts = existing.split("\n---\n") if existing else []
    if new not in parts:
        parts.append(new)
    return "\n---\n".join(parts)


def _dedupe_search_fragments(fragments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int]] = set()
    for fragment in fragments:
        if not isinstance(fragment, dict):
            continue
        text_value = fragment.get("text")
        match_type = fragment.get("match_type")
        char_offset = fragment.get("char_offset")
        if not isinstance(text_value, str) or not isinstance(match_type, str):
            continue
        if not isinstance(char_offset, int):
            char_offset = 0
        key = (text_value, match_type, char_offset)
        if key in seen:
            continue
        seen.add(key)
        deduped.append({"text": text_value, "match_type": match_type, "char_offset": char_offset})
    return deduped


def _format_title_search_result_payload(item: Any) -> list[str]:
    title_str = item.title if item.title else "без названия"
    preview = item.raw_text_preview.strip()[:300] if item.raw_text_preview else ""
    lines = [
        f"- dream_id: {item.dream_id}",
        f"  date: {item.date or 'unknown'}",
        f"  title: {title_str}",
    ]
    if preview:
        lines.append(f"  preview: {preview}")
    return lines


def _format_dream_detail_payload(detail: Any) -> str:
    theme_names = ", ".join(t.category_name for t in detail.themes) or "none"
    raw_text_clean = detail.raw_text.replace("*", "").replace("<", "")
    lines = [
        f"Dream {detail.id}\n"
        f"Date: {detail.date or 'unknown'}\n"
        f"Title: {detail.title}\n"
        f"Words: {detail.word_count}\n"
        f"Themes: {theme_names}\n"
        f"Text: {raw_text_clean[:2000]}"
    ]
    if detail.notes:
        lines.append("Notes:")
        lines.extend(f"- {note}" for note in detail.notes)
    return "\n".join(lines)


def _search_evidence_text(item: Any) -> str:
    if item.quote:
        return item.quote

    fragments = item.matched_fragments if isinstance(item.matched_fragments, list) else []
    fragment_texts = [
        str(fragment["text"]).strip()
        for fragment in fragments
        if isinstance(fragment, dict) and str(fragment.get("text", "")).strip()
    ]
    if fragment_texts:
        return "\n---\n".join(fragment_texts)

    return item.chunk_text.strip()


def _is_explicit_create_request(request_text: str | None) -> bool:
    if not request_text:
        return False

    text = request_text.casefold()
    explicit_phrases = (
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
    if any(phrase in text for phrase in explicit_phrases):
        return True

    return _has_natural_dream_opening(text)


_WORD_RE = re.compile(r"[0-9A-Za-zА-Яа-яЁё]+")
_NATURAL_DREAM_OPENINGS = (
    "сегодня мне приснилось",
    "сегодня мне приснилась",
    "сегодня мне приснился",
    "сегодня мне приснились",
    "мне приснилось",
    "мне приснилась",
    "мне приснился",
    "мне приснились",
    "мне снилось",
    "мне снилась",
    "мне снился",
    "мне снились",
    "приснился сон",
    "приснились сны",
    "приснилось, что",
)


def _has_natural_dream_opening(text: str) -> bool:
    for opening in _NATURAL_DREAM_OPENINGS:
        index = text.find(opening)
        if index < 0:
            continue
        tail = text[index + len(opening) :]
        if len(_WORD_RE.findall(tail)) >= 1:
            return True

    return False

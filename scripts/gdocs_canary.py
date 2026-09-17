#!/usr/bin/env python3
"""Run a bounded Google Docs durability canary against a disposable document.

The script intentionally mutates the selected document. It refuses to run
against the configured primary archive unless the operator explicitly opts in.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import uuid
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


class CanaryFailure(RuntimeError):
    """Raised when the canary observes an unsafe Google Docs behavior."""


@dataclass(frozen=True)
class GDocsCanaryReport:
    document_id: str
    document_title: str
    metadata_change_marker: str
    run_id: str
    dream_inserted: bool
    dream_duplicate_blocked: bool
    note_inserted_or_adopted: bool
    note_duplicate_blocked: bool
    runtime_source_switched: bool


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Verify Google Docs named-range idempotency and runtime source switching "
            "against a disposable document."
        )
    )
    parser.add_argument(
        "--doc-id",
        default=os.environ.get("GOOGLE_CANARY_DOC_ID", ""),
        help="Disposable Google Doc URL or bare id. Defaults to GOOGLE_CANARY_DOC_ID.",
    )
    parser.add_argument(
        "--runtime-state-file",
        default="",
        help=(
            "Optional runtime state file to exercise. Defaults to a temporary file so "
            "the canonical bot/API runtime state is not mutated."
        ),
    )
    parser.add_argument(
        "--allow-primary",
        action="store_true",
        help="Allow running against the configured primary GOOGLE_DOC_ID.",
    )
    parser.add_argument(
        "--run-id",
        default="",
        help="Stable canary id for repeat debugging. Defaults to a random short id.",
    )
    return parser.parse_args(argv)


def _document_text(document: Mapping[str, Any]) -> str:
    chunks: list[str] = []
    for block in document.get("body", {}).get("content", []):
        paragraph = block.get("paragraph") if isinstance(block, Mapping) else None
        if not isinstance(paragraph, Mapping):
            continue
        for element in paragraph.get("elements", []):
            text_run = element.get("textRun") if isinstance(element, Mapping) else None
            if isinstance(text_run, Mapping):
                chunks.append(str(text_run.get("content") or ""))
    return "".join(chunks)


def _validate_disposable_doc(
    *,
    doc_id: str,
    primary_doc_id: str,
    allow_primary: bool,
) -> None:
    if not doc_id:
        raise CanaryFailure("Provide --doc-id or GOOGLE_CANARY_DOC_ID for a disposable document")
    if doc_id == primary_doc_id and not allow_primary:
        raise CanaryFailure(
            "Refusing to run against primary GOOGLE_DOC_ID. Use a disposable doc or pass "
            "--allow-primary for an intentional operator drill."
        )


def run_gdocs_canary(
    *,
    client: Any,
    doc_id: str,
    run_id: str,
    date_str: str,
    switch_runtime_source: Any,
) -> GDocsCanaryReport:
    """Execute the live Google Docs canary using an injected client."""

    metadata = client.fetch_document_metadata(doc_id)
    title = f"Canary {run_id}"
    heading = f"{date_str} - {title}"
    body = f"Phase C canary body {run_id}"
    mutated_body = f"{body} mutated duplicate"
    dream_key = f"phase-c-canary-dream:{run_id}"

    dream_inserted = client.append_dream_entry(
        doc_id,
        date_str,
        title,
        body,
        idempotency_key=dream_key,
    )
    dream_duplicate_result = client.append_dream_entry(
        doc_id,
        date_str,
        title,
        mutated_body,
        idempotency_key=dream_key,
    )
    if dream_duplicate_result:
        raise CanaryFailure("Dream named-range idempotency failed: duplicate insert returned true")

    after_dream = _document_text(client.fetch_document_resource(doc_id))
    if after_dream.count(body) != 1 or mutated_body in after_dream:
        raise CanaryFailure("Dream named-range idempotency failed: duplicate body appeared")

    note_text = f"[Canary {run_id}]: named range note"
    duplicate_note_text = f"{note_text} duplicate"
    note_key = f"phase-c-canary-note:{run_id}"
    note_inserted = client.insert_text_under_heading(
        doc_id,
        heading=heading,
        text=note_text,
        idempotency_key=note_key,
    )
    if not note_inserted:
        raise CanaryFailure("Canary dream heading was not found for note insertion")

    note_duplicate_adopted = client.insert_text_under_heading(
        doc_id,
        heading=heading,
        text=duplicate_note_text,
        idempotency_key=note_key,
    )
    if not note_duplicate_adopted:
        raise CanaryFailure("Note named-range adoption failed: second call did not adopt")

    after_note = _document_text(client.fetch_document_resource(doc_id))
    if after_note.count(note_text) != 1 or duplicate_note_text in after_note:
        raise CanaryFailure("Note named-range idempotency failed: duplicate note appeared")

    runtime_source_switched = bool(switch_runtime_source(doc_id))
    if not runtime_source_switched:
        raise CanaryFailure("Runtime source switch did not select the canary document")

    return GDocsCanaryReport(
        document_id=doc_id,
        document_title=str(getattr(metadata, "title", "") or doc_id),
        metadata_change_marker=str(getattr(metadata, "change_marker", "") or ""),
        run_id=run_id,
        dream_inserted=bool(dream_inserted),
        dream_duplicate_blocked=True,
        note_inserted_or_adopted=True,
        note_duplicate_blocked=True,
        runtime_source_switched=True,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    temporary_state: tempfile.TemporaryDirectory[str] | None = None
    if args.runtime_state_file:
        os.environ["RUNTIME_STATE_FILE"] = str(Path(args.runtime_state_file).expanduser())
    elif not os.environ.get("RUNTIME_STATE_FILE"):
        temporary_state = tempfile.TemporaryDirectory(prefix="gdocs-canary-state-")
        os.environ["RUNTIME_STATE_FILE"] = str(Path(temporary_state.name) / "runtime-state.json")

    try:
        from app.services.gdocs_client import GDocsClient
        from app.shared.config import (
            extract_google_doc_id,
            get_all_doc_ids,
            get_effective_google_doc_id,
            get_settings,
            set_google_doc_id_override,
        )

        settings = get_settings()
        doc_id = extract_google_doc_id(str(args.doc_id or ""))
        _validate_disposable_doc(
            doc_id=doc_id,
            primary_doc_id=extract_google_doc_id(settings.GOOGLE_DOC_ID),
            allow_primary=bool(args.allow_primary),
        )

        def switch_runtime_source(candidate_doc_id: str) -> bool:
            set_google_doc_id_override(candidate_doc_id)
            return (
                get_effective_google_doc_id() == candidate_doc_id
                and get_all_doc_ids()[0] == candidate_doc_id
            )

        run_id = args.run_id.strip() or uuid.uuid4().hex[:10]
        report = run_gdocs_canary(
            client=GDocsClient(settings=settings),
            doc_id=doc_id,
            run_id=run_id,
            date_str=datetime.now().strftime("%d.%m.%y"),
            switch_runtime_source=switch_runtime_source,
        )
        print(json.dumps(asdict(report), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except CanaryFailure as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 2
    finally:
        if temporary_state is not None:
            temporary_state.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())

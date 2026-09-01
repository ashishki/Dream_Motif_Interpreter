from __future__ import annotations

from types import SimpleNamespace

import pytest

from scripts.gdocs_canary import (
    CanaryFailure,
    _validate_disposable_doc,
    run_gdocs_canary,
)


class FakeGDocsClient:
    def __init__(self) -> None:
        self.text = ""
        self.append_calls: list[dict[str, str]] = []
        self.note_calls: list[dict[str, str]] = []

    def fetch_document_metadata(self, doc_id: str) -> SimpleNamespace:
        return SimpleNamespace(
            document_id=doc_id,
            title="Disposable Canary",
            change_marker="rev-1",
        )

    def append_dream_entry(
        self,
        doc_id: str,
        date_str: str,
        title: str,
        body: str,
        *,
        idempotency_key: str | None = None,
    ) -> bool:
        self.append_calls.append(
            {
                "doc_id": doc_id,
                "date_str": date_str,
                "title": title,
                "body": body,
                "idempotency_key": idempotency_key or "",
            }
        )
        if len(self.append_calls) == 1:
            self.text += f"{date_str} - {title}\n\n{body}\n"
            return True
        return False

    def insert_text_under_heading(
        self,
        doc_id: str,
        *,
        heading: str,
        text: str,
        idempotency_key: str | None = None,
    ) -> bool:
        self.note_calls.append(
            {
                "doc_id": doc_id,
                "heading": heading,
                "text": text,
                "idempotency_key": idempotency_key or "",
            }
        )
        if len(self.note_calls) == 1:
            self.text += f"{text}\n"
        return True

    def fetch_document_resource(self, doc_id: str) -> dict:
        del doc_id
        return {
            "body": {
                "content": [
                    {
                        "paragraph": {
                            "elements": [{"textRun": {"content": self.text}}],
                        }
                    }
                ]
            }
        }


class DuplicateDreamClient(FakeGDocsClient):
    def append_dream_entry(
        self,
        doc_id: str,
        date_str: str,
        title: str,
        body: str,
        *,
        idempotency_key: str | None = None,
    ) -> bool:
        inserted = super().append_dream_entry(
            doc_id,
            date_str,
            title,
            body,
            idempotency_key=idempotency_key,
        )
        if len(self.append_calls) == 2:
            self.text += f"{body}\n"
            return True
        return inserted


def test_gdocs_canary_verifies_named_ranges_and_runtime_switch() -> None:
    selected_doc_ids: list[str] = []
    report = run_gdocs_canary(
        client=FakeGDocsClient(),
        doc_id="disposable-doc",
        run_id="abc123",
        date_str="01.09.26",
        switch_runtime_source=lambda doc_id: selected_doc_ids.append(doc_id) is None,
    )

    assert report.document_id == "disposable-doc"
    assert report.document_title == "Disposable Canary"
    assert report.metadata_change_marker == "rev-1"
    assert report.dream_inserted is True
    assert report.dream_duplicate_blocked is True
    assert report.note_inserted_or_adopted is True
    assert report.note_duplicate_blocked is True
    assert report.runtime_source_switched is True
    assert selected_doc_ids == ["disposable-doc"]


def test_gdocs_canary_refuses_primary_doc_without_explicit_opt_in() -> None:
    with pytest.raises(CanaryFailure, match="primary GOOGLE_DOC_ID"):
        _validate_disposable_doc(
            doc_id="primary-doc",
            primary_doc_id="primary-doc",
            allow_primary=False,
        )


def test_gdocs_canary_detects_duplicate_dream_body() -> None:
    with pytest.raises(CanaryFailure, match="duplicate insert returned true"):
        run_gdocs_canary(
            client=DuplicateDreamClient(),
            doc_id="disposable-doc",
            run_id="abc123",
            date_str="01.09.26",
            switch_runtime_source=lambda _doc_id: True,
        )

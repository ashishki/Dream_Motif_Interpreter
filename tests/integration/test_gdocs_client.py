import os

import pytest

from app.services.gdocs_client import GDocsClient


@pytest.mark.skipif(
    not os.getenv("GOOGLE_REFRESH_TOKEN")
    or os.getenv("GOOGLE_REFRESH_TOKEN") == "test-google-refresh-token",
    reason="requires real Google credentials",
)
def test_fetch_document_returns_paragraphs() -> None:
    paragraphs = GDocsClient().fetch_document()

    assert isinstance(paragraphs, list)
    assert paragraphs
    assert all(isinstance(paragraph, str) for paragraph in paragraphs)
    assert all(paragraph for paragraph in paragraphs)

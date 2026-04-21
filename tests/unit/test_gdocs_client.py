from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError
from httplib2 import Response

from app.services.gdocs_client import GDocsAuthError, GDocsClient


def _build_settings(**overrides: str) -> SimpleNamespace:
    defaults = {
        "GOOGLE_CLIENT_ID": "client-id-123",
        "GOOGLE_CLIENT_SECRET": "client-secret-456",
        "GOOGLE_REFRESH_TOKEN": "refresh-token-789",
        "GOOGLE_SERVICE_ACCOUNT_FILE": "",
        "GOOGLE_DOC_ID": "doc-id-abc",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _build_http_error(status_code: int) -> HttpError:
    return HttpError(Response({"status": str(status_code)}), b'{"error":"auth"}')


def test_fetch_document_raises_on_invalid_token() -> None:
    client = GDocsClient(settings=_build_settings(GOOGLE_REFRESH_TOKEN="invalid-token"))

    with patch(
        "app.services.gdocs_client.Credentials.refresh",
        side_effect=RefreshError("invalid_grant"),
    ):
        with pytest.raises(GDocsAuthError):
            client.fetch_document()


def test_builds_service_account_credentials_when_configured() -> None:
    client = GDocsClient(
        settings=_build_settings(
            GOOGLE_SERVICE_ACCOUNT_FILE="/tmp/service-account.json",
            GOOGLE_CLIENT_ID="",
            GOOGLE_CLIENT_SECRET="",
            GOOGLE_REFRESH_TOKEN="",
        )
    )

    with (
        patch(
            "app.services.gdocs_client.ServiceAccountCredentials.from_service_account_file",
            return_value=Mock(),
        ) as mocked_loader,
        patch("app.services.gdocs_client.Path.exists", return_value=True),
    ):
        client._build_credentials()

    mocked_loader.assert_called_once_with(
        "/tmp/service-account.json",
        scopes=[
            "https://www.googleapis.com/auth/documents.readonly",
            "https://www.googleapis.com/auth/drive.readonly",
        ],
    )


def test_service_account_file_must_exist() -> None:
    client = GDocsClient(
        settings=_build_settings(
            GOOGLE_SERVICE_ACCOUNT_FILE="/tmp/missing-service-account.json",
            GOOGLE_CLIENT_ID="",
            GOOGLE_CLIENT_SECRET="",
            GOOGLE_REFRESH_TOKEN="",
        )
    )

    with pytest.raises(GDocsAuthError, match="service account file not found"):
        client._build_credentials()


@pytest.mark.parametrize("status_code", [401, 403])
def test_fetch_document_raises_on_auth_http_errors(status_code: int) -> None:
    client = GDocsClient(settings=_build_settings())
    mocked_service = Mock()
    mocked_service.documents.return_value.get.return_value.execute.side_effect = _build_http_error(
        status_code
    )

    with patch.object(client, "_build_docs_service", return_value=mocked_service):
        with pytest.raises(GDocsAuthError):
            client.fetch_document()


def test_non_auth_http_error_propagates() -> None:
    client = GDocsClient(settings=_build_settings())
    mocked_service = Mock()
    http_error = _build_http_error(500)
    mocked_service.documents.return_value.get.return_value.execute.side_effect = http_error

    with patch.object(client, "_build_docs_service", return_value=mocked_service):
        with pytest.raises(HttpError) as exc_info:
            client.fetch_document()

    assert exc_info.value is http_error


def test_no_credentials_in_logs(capsys: pytest.CaptureFixture[str]) -> None:
    settings = _build_settings()
    client = GDocsClient(settings=settings)
    mocked_service = Mock()
    mocked_service.documents.return_value.get.return_value.execute.return_value = {
        "body": {
            "content": [
                {
                    "paragraph": {
                        "elements": [
                            {"textRun": {"content": "First paragraph\n"}},
                            {"textRun": {"content": ""}},
                        ]
                    }
                },
                {"paragraph": {"elements": [{"textRun": {"content": "\n"}}]}},
                {"paragraph": {"elements": [{"textRun": {"content": "Second paragraph"}}]}},
            ]
        }
    }

    with patch.object(client, "_build_docs_service", return_value=mocked_service):
        paragraphs = client.fetch_document()

    captured = capsys.readouterr()
    output = captured.out + captured.err

    assert paragraphs == ["First paragraph", "Second paragraph"]
    assert settings.GOOGLE_CLIENT_ID not in output
    assert settings.GOOGLE_CLIENT_SECRET not in output
    assert settings.GOOGLE_REFRESH_TOKEN not in output


def test_fetch_document_metadata_returns_lightweight_change_marker() -> None:
    client = GDocsClient(settings=_build_settings())
    mocked_service = Mock()
    mocked_service.files.return_value.get.return_value.execute.return_value = {
        "id": "doc-id-abc",
        "name": "Dream Journal",
        "modifiedTime": "2026-04-21T12:34:56Z",
        "version": "17",
        "headRevisionId": "rev-17",
    }

    with patch.object(client, "_build_drive_service", return_value=mocked_service):
        metadata = client.fetch_document_metadata()

    assert metadata.document_id == "doc-id-abc"
    assert metadata.title == "Dream Journal"
    assert metadata.version == "17"
    assert metadata.head_revision_id == "rev-17"
    assert metadata.change_marker == "rev-17"

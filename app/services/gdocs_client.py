from collections.abc import Mapping
from pathlib import Path
from typing import Any

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.shared.config import Settings, get_settings
from app.shared.tracing import get_logger, get_tracer

GOOGLE_DOCS_READONLY_SCOPE = "https://www.googleapis.com/auth/documents.readonly"
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"

logger = get_logger(__name__)


class GDocsAuthError(Exception):
    """Raised when Google Docs authentication fails."""


class GDocsClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._tracer = get_tracer(__name__)

    def fetch_document(self) -> list[str]:
        with self._tracer.start_as_current_span("gdocs.fetch_document"):
            logger.info("Fetching Google Docs document")

            try:
                with self._tracer.start_as_current_span("gdocs.build_service"):
                    service = self._build_docs_service()
                with self._tracer.start_as_current_span("gdocs.documents.get"):
                    document = (
                        service.documents().get(documentId=self._settings.GOOGLE_DOC_ID).execute()
                    )
            except RefreshError as exc:
                logger.warning("Google Docs authentication failed during token refresh")
                raise GDocsAuthError("Google Docs authentication failed") from exc
            except HttpError as exc:
                status_code = _get_status_code(exc)
                if status_code in {401, 403}:
                    logger.warning(
                        "Google Docs authentication failed with HTTP status",
                        status_code=status_code,
                    )
                    raise GDocsAuthError("Google Docs authentication failed") from exc
                logger.error(
                    "Google Docs API request failed with HTTP status", status_code=status_code
                )
                raise

            paragraphs = _extract_paragraphs(document)
            logger.info("Fetched Google Docs document")
            return paragraphs

    def _build_docs_service(self) -> Any:
        credentials = self._build_credentials()
        return build("docs", "v1", credentials=credentials, cache_discovery=False)

    def _build_credentials(self) -> Credentials:
        service_account_file = self._settings.GOOGLE_SERVICE_ACCOUNT_FILE.strip()
        if service_account_file:
            return self._build_service_account_credentials(service_account_file)

        with self._tracer.start_as_current_span("gdocs.refresh_credentials"):
            credentials = Credentials(
                token=None,
                refresh_token=self._settings.GOOGLE_REFRESH_TOKEN,
                token_uri=GOOGLE_TOKEN_URI,
                client_id=self._settings.GOOGLE_CLIENT_ID,
                client_secret=self._settings.GOOGLE_CLIENT_SECRET,
                scopes=[GOOGLE_DOCS_READONLY_SCOPE],
            )
            credentials.refresh(Request())
            return credentials

    def _build_service_account_credentials(self, credential_path: str) -> ServiceAccountCredentials:
        with self._tracer.start_as_current_span("gdocs.load_service_account_credentials"):
            path = Path(credential_path)
            if not path.exists():
                raise GDocsAuthError("Google Docs service account file not found")

            return ServiceAccountCredentials.from_service_account_file(
                str(path),
                scopes=[GOOGLE_DOCS_READONLY_SCOPE],
            )


def _extract_paragraphs(document: Mapping[str, Any]) -> list[str]:
    paragraphs: list[str] = []
    body = document.get("body", {})

    for block in body.get("content", []):
        paragraph = block.get("paragraph")
        if paragraph is None:
            continue

        text = "".join(
            element.get("textRun", {}).get("content", "")
            for element in paragraph.get("elements", [])
        ).strip()
        if text:
            paragraphs.append(text)

    return paragraphs


def _get_status_code(exc: HttpError) -> int | None:
    status = getattr(exc.resp, "status", None)
    try:
        return int(status) if status is not None else None
    except (TypeError, ValueError):
        return None

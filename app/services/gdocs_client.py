from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.retrieval.types import FetchedSourceDocument, SourceDocumentRef
from app.shared.config import Settings, get_settings
from app.shared.tracing import get_logger, get_tracer

GOOGLE_DOCS_READONLY_SCOPE = "https://www.googleapis.com/auth/documents.readonly"
GOOGLE_DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
GOOGLE_DOCS_READWRITE_SCOPE = "https://www.googleapis.com/auth/documents"
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"
GOOGLE_DOCS_SOURCE_TYPE = "google_doc"

logger = get_logger(__name__)


class GDocsAuthError(Exception):
    """Raised when Google Docs authentication fails."""


class GDocsWriteError(Exception):
    """Raised when writing to Google Docs fails."""


@dataclass(frozen=True)
class GoogleDocMetadata:
    document_id: str
    title: str
    updated_at: datetime | None
    version: str | None
    head_revision_id: str | None

    @property
    def change_marker(self) -> str:
        if self.head_revision_id:
            return self.head_revision_id
        if self.version:
            return self.version
        if self.updated_at is not None:
            return self.updated_at.isoformat()
        return self.document_id


class GDocsClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._tracer = get_tracer(__name__)

    def fetch_document(self) -> list[str]:
        document = self.fetch_document_resource()
        paragraphs = _extract_paragraphs(document)
        logger.info("Fetched Google Docs document")
        return paragraphs

    @property
    def document_id(self) -> str:
        return self._settings.GOOGLE_DOC_ID

    def fetch_document_resource(self, document_id: str | None = None) -> Mapping[str, Any]:
        with self._tracer.start_as_current_span("gdocs.fetch_document"):
            logger.info("Fetching Google Docs document")

            try:
                with self._tracer.start_as_current_span("gdocs.build_service"):
                    service = self._build_docs_service()
                with self._tracer.start_as_current_span("gdocs.documents.get"):
                    document = (
                        service.documents()
                        .get(documentId=document_id or self._settings.GOOGLE_DOC_ID)
                        .execute()
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

            return document

    def fetch_document_metadata(self, document_id: str | None = None) -> GoogleDocMetadata:
        resolved_document_id = document_id or self._settings.GOOGLE_DOC_ID
        with self._tracer.start_as_current_span("gdocs.fetch_document_metadata"):
            logger.info("Fetching Google Docs metadata")

            try:
                with self._tracer.start_as_current_span("gdocs.build_drive_service"):
                    service = self._build_drive_service()
                with self._tracer.start_as_current_span("gdocs.files.get"):
                    payload = (
                        service.files()
                        .get(
                            fileId=resolved_document_id,
                            fields="id,name,modifiedTime,version,headRevisionId",
                        )
                        .execute()
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
                    "Google Docs metadata request failed with HTTP status",
                    status_code=status_code,
                )
                raise

        return GoogleDocMetadata(
            document_id=str(payload.get("id") or resolved_document_id),
            title=str(payload.get("name") or resolved_document_id),
            updated_at=_parse_updated_at(payload),
            version=_clean_optional_str(payload.get("version")),
            head_revision_id=_clean_optional_str(payload.get("headRevisionId")),
        )

    def append_text(self, doc_id: str, text: str) -> None:
        """Append text at the end of the Google Doc."""
        with self._tracer.start_as_current_span("gdocs.append_text"):
            logger.info("Appending text to Google Docs document", document_id=doc_id)
            try:
                service = self._build_docs_service()
                document = service.documents().get(documentId=doc_id).execute()
                body_content = document.get("body", {}).get("content", [])
                end_index = 1
                if body_content:
                    last = body_content[-1]
                    end_index = last.get("endIndex", 1)
                    end_index = max(1, end_index - 1)

                insert_text = "\n\n" + text
                requests = [
                    {
                        "insertText": {
                            "location": {"index": end_index},
                            "text": insert_text,
                        }
                    }
                ]
                service.documents().batchUpdate(
                    documentId=doc_id,
                    body={"requests": requests},
                ).execute()
                logger.info(
                    "Successfully appended text to Google Docs document", document_id=doc_id
                )
            except RefreshError as exc:
                logger.warning("Google Docs authentication failed during append")
                raise GDocsWriteError("Google Docs authentication failed during write") from exc
            except HttpError as exc:
                status_code = _get_status_code(exc)
                if status_code in {401, 403}:
                    logger.warning(
                        "Google Docs write permission denied",
                        status_code=status_code,
                        document_id=doc_id,
                    )
                    raise GDocsWriteError(
                        f"Google Docs write permission denied (HTTP {status_code}). "
                        "Ensure credentials have documents write scope."
                    ) from exc
                if status_code == 404:
                    raise GDocsWriteError(f"Google Docs document not found: {doc_id}") from exc
                logger.error(
                    "Google Docs batchUpdate failed",
                    status_code=status_code,
                    document_id=doc_id,
                )
                raise GDocsWriteError(
                    f"Google Docs batchUpdate failed (HTTP {status_code})"
                ) from exc

    def append_dream_entry(self, doc_id: str, date_str: str, title: str, body: str) -> None:
        """Append a dream entry with the title styled as Heading 1."""
        with self._tracer.start_as_current_span("gdocs.append_dream_entry"):
            logger.info("Appending dream entry to Google Docs document", document_id=doc_id)
            try:
                service = self._build_docs_service()
                document = service.documents().get(documentId=doc_id).execute()
                body_content = document.get("body", {}).get("content", [])
                end_index = 1
                if body_content:
                    last = body_content[-1]
                    end_index = max(1, last.get("endIndex", 1) - 1)

                # Layout: \n\n{date_str} - {title}\n\n{body}
                prefix = "\n\n"
                heading = f"{date_str} - {title}"
                title_line = f"{heading}\n\n"
                full_text = prefix + title_line + body

                title_start = end_index + len(prefix)
                title_end = title_start + len(heading) + 1  # +1 for trailing \n

                requests: list[dict] = [
                    {
                        "insertText": {
                            "location": {"index": end_index},
                            "text": full_text,
                        }
                    },
                    {
                        "updateParagraphStyle": {
                            "range": {
                                "startIndex": title_start,
                                "endIndex": title_end,
                            },
                            "paragraphStyle": {"namedStyleType": "HEADING_1"},
                            "fields": "namedStyleType",
                        }
                    },
                ]
                service.documents().batchUpdate(
                    documentId=doc_id,
                    body={"requests": requests},
                ).execute()
                logger.info(
                    "Successfully appended dream entry to Google Docs document", document_id=doc_id
                )
            except RefreshError as exc:
                logger.warning("Google Docs authentication failed during append")
                raise GDocsWriteError("Google Docs authentication failed during write") from exc
            except HttpError as exc:
                status_code = _get_status_code(exc)
                if status_code in {401, 403}:
                    logger.warning(
                        "Google Docs write permission denied",
                        status_code=status_code,
                        document_id=doc_id,
                    )
                    raise GDocsWriteError(
                        f"Google Docs write permission denied (HTTP {status_code}). "
                        "Ensure credentials have documents write scope."
                    ) from exc
                if status_code == 404:
                    raise GDocsWriteError(f"Google Docs document not found: {doc_id}") from exc
                logger.error(
                    "Google Docs batchUpdate failed",
                    status_code=status_code,
                    document_id=doc_id,
                )
                raise GDocsWriteError(
                    f"Google Docs batchUpdate failed (HTTP {status_code})"
                ) from exc

    def _build_docs_service(self) -> Any:
        credentials = self._build_credentials()
        return build("docs", "v1", credentials=credentials, cache_discovery=False)

    def _build_drive_service(self) -> Any:
        credentials = self._build_credentials()
        return build("drive", "v3", credentials=credentials, cache_discovery=False)

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
                scopes=[
                    GOOGLE_DOCS_READONLY_SCOPE,
                    GOOGLE_DOCS_READWRITE_SCOPE,
                    GOOGLE_DRIVE_READONLY_SCOPE,
                ],
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
                scopes=[
                    GOOGLE_DOCS_READONLY_SCOPE,
                    GOOGLE_DOCS_READWRITE_SCOPE,
                    GOOGLE_DRIVE_READONLY_SCOPE,
                ],
            )


class SingleGoogleDocConnector:
    def __init__(
        self, client: GDocsClient | None = None, *, document_id: str | None = None
    ) -> None:
        self._client = client or GDocsClient()
        self._document_id = document_id or self._client.document_id
        self._cached_document: Mapping[str, Any] | None = None

    def list_documents(self) -> list[SourceDocumentRef]:
        document = self._get_document(self._document_id)
        return [_build_document_ref(document, document_id=self._document_id)]

    def fetch_document(self, document: SourceDocumentRef) -> FetchedSourceDocument:
        source_document = self._get_document(document.external_id)
        return _build_fetched_document(source_document, document_id=document.external_id)

    def _get_document(self, document_id: str) -> Mapping[str, Any]:
        if self._cached_document is None or document_id != self._document_id:
            self._cached_document = self._client.fetch_document_resource(document_id)
        return self._cached_document


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


def _build_document_ref(document: Mapping[str, Any], *, document_id: str) -> SourceDocumentRef:
    return SourceDocumentRef(
        source_type=GOOGLE_DOCS_SOURCE_TYPE,
        external_id=document_id,
        title=_get_title(document, document_id=document_id),
        source_path=_build_source_path(document_id),
        updated_at=_parse_updated_at(document),
    )


def _build_fetched_document(
    document: Mapping[str, Any], *, document_id: str
) -> FetchedSourceDocument:
    return FetchedSourceDocument(
        source_type=GOOGLE_DOCS_SOURCE_TYPE,
        external_id=document_id,
        title=_get_title(document, document_id=document_id),
        source_path=_build_source_path(document_id),
        updated_at=_parse_updated_at(document),
        raw_contents=_extract_paragraphs(document),
    )


def _get_title(document: Mapping[str, Any], *, document_id: str) -> str:
    title = document.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    return document_id


def _build_source_path(document_id: str) -> str:
    return f"documents/{document_id}"


def _parse_updated_at(document: Mapping[str, Any]) -> datetime | None:
    raw_updated_at = document.get("updatedAt") or document.get("modifiedTime")
    if not isinstance(raw_updated_at, str) or not raw_updated_at.strip():
        return None

    normalized_value = raw_updated_at.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized_value)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _get_status_code(exc: HttpError) -> int | None:
    status = getattr(exc.resp, "status", None)
    try:
        return int(status) if status is not None else None
    except (TypeError, ValueError):
        return None


def _clean_optional_str(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None

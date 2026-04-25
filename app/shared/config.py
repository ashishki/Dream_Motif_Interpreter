import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel
from pydantic import Field
from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_logger = logging.getLogger(__name__)

_GDOC_URL_RE = re.compile(r"docs\.google\.com/document/d/([a-zA-Z0-9_-]+)")
_EXTRA_DOCS_FILE = Path(__file__).parent.parent.parent / "runtime_extra_docs.json"


def extract_google_doc_id(value: str) -> str:
    """Return the bare doc ID from either a full Google Docs URL or a plain ID."""
    match = _GDOC_URL_RE.search(value)
    if match:
        return match.group(1)
    return value.strip()


class OperatorParserProfileAssignments(BaseModel):
    clients: dict[str, str] = Field(default_factory=dict)
    source_containers: dict[str, str] = Field(default_factory=dict)


class Settings(BaseSettings):
    DATABASE_URL: str
    REDIS_URL: str
    ANTHROPIC_API_KEY: str
    OPENAI_API_KEY: str
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REFRESH_TOKEN: str = ""
    GOOGLE_SERVICE_ACCOUNT_FILE: str = ""
    GOOGLE_DOC_ID: str
    GOOGLE_DOC_IDS: Annotated[list[str], NoDecode] = Field(default_factory=list)
    GOOGLE_OWNER_EMAIL: str = ""  # Google account to share bot-created docs with
    SECRET_KEY: str
    ENV: str
    AUTO_SYNC_ENABLED: bool = False
    AUTO_SYNC_INTERVAL_SECONDS: int = 300

    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_ALLOWED_CHAT_ID: int = 0
    VOICE_MEDIA_DIR: str = "/tmp/dream_voice"
    VOICE_RETENTION_SECONDS: int = 3600

    EMBEDDING_MODEL: str = "text-embedding-3-small"
    RETRIEVAL_THRESHOLD: float = 0.20
    MAX_INDEX_AGE_HOURS: int = 24
    BULK_CONFIRM_TOKEN_TTL_SECONDS: int = 600

    # Feature flags are evaluated once per process because get_settings() is lru-cached.
    MOTIF_INDUCTION_ENABLED: bool = True
    RESEARCH_API_BASE_URL: str = "https://api.tavily.com"
    RESEARCH_API_KEY: str = ""
    RESEARCH_AUGMENTATION_ENABLED: bool = False
    OPERATOR_PARSER_PROFILE_ASSIGNMENTS: OperatorParserProfileAssignments = Field(
        default_factory=OperatorParserProfileAssignments
    )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("GOOGLE_DOC_IDS", mode="before")
    @classmethod
    def _parse_google_doc_ids(cls, v: object) -> list[str]:
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        if isinstance(v, list):
            return [s.strip() for s in v if isinstance(s, str) and s.strip()]
        return []

    def resolve_operator_parser_profile(
        self,
        *,
        client_id: str,
        source_path: str,
    ) -> str | None:
        client_profile = self.OPERATOR_PARSER_PROFILE_ASSIGNMENTS.clients.get(client_id)
        if client_profile is not None:
            return client_profile

        source_container = _source_container_from_path(source_path)
        if source_container is None:
            return None
        return self.OPERATOR_PARSER_PROFILE_ASSIGNMENTS.source_containers.get(source_container)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


# Runtime override for GOOGLE_DOC_ID - settable without process restart
_google_doc_id_override: str | None = None
_google_doc_ids_override: list[str] | None = None


def get_effective_google_doc_id() -> str:
    """Return the currently active GOOGLE_DOC_ID (runtime override takes precedence)."""
    if _google_doc_id_override is not None:
        return _google_doc_id_override
    return get_settings().GOOGLE_DOC_ID


def set_google_doc_id_override(doc_id: str) -> None:
    """Override GOOGLE_DOC_ID at runtime without restarting the process."""
    global _google_doc_id_override
    _google_doc_id_override = doc_id


def set_google_doc_ids_override(doc_ids: list[str]) -> None:
    global _google_doc_ids_override
    _google_doc_ids_override = doc_ids
    _save_extra_docs(doc_ids)


def _save_extra_docs(doc_ids: list[str]) -> None:
    try:
        _EXTRA_DOCS_FILE.write_text(json.dumps(doc_ids), encoding="utf-8")
    except Exception:
        _logger.warning("Failed to persist extra doc IDs to %s", _EXTRA_DOCS_FILE)


def _load_extra_docs() -> list[str]:
    try:
        if _EXTRA_DOCS_FILE.exists():
            data = json.loads(_EXTRA_DOCS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return [str(d) for d in data if d]
    except Exception:
        _logger.warning("Failed to load extra doc IDs from %s", _EXTRA_DOCS_FILE)
    return []


def get_all_doc_ids() -> list[str]:
    primary = get_effective_google_doc_id()
    if _google_doc_ids_override is not None:
        extras = _google_doc_ids_override
    else:
        extras = get_settings().GOOGLE_DOC_IDS or _load_extra_docs()
    seen: set[str] = {primary}
    result = [primary]
    for doc_id in extras:
        if doc_id and doc_id not in seen:
            seen.add(doc_id)
            result.append(doc_id)
    return result


def _source_container_from_path(source_path: str) -> str | None:
    normalized_path = source_path.strip("/")
    if not normalized_path or "/" not in normalized_path:
        return None
    return normalized_path.rsplit("/", 1)[0]

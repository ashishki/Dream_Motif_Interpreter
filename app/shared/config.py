import json
import logging
import os
import re
import tempfile
import threading
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover - production containers are Linux.
    fcntl = None  # type: ignore[assignment]

from pydantic import BaseModel
from pydantic import Field
from pydantic import field_validator
from pydantic import model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_logger = logging.getLogger(__name__)
_runtime_state_lock = threading.RLock()

_GDOC_URL_RE = re.compile(r"docs\.google\.com/document/d/([a-zA-Z0-9_-]+)")
_EXTRA_DOCS_FILE = Path(__file__).parent.parent.parent / "runtime_extra_docs.json"
_TEST_ENVIRONMENTS = {"test", "testing"}
_MIN_SECRET_KEY_BYTES = 32
_MIN_SECRET_KEY_UNIQUE_CHARACTERS = 8
_DISALLOWED_SECRET_KEY_MARKERS = (
    "change-me",
    "changeme",
    "example",
    "placeholder",
    "replace-me",
    "test-secret",
)


def extract_google_doc_id(value: str) -> str:
    """Return the bare doc ID from either a full Google Docs URL or a plain ID."""
    match = _GDOC_URL_RE.search(value)
    if match:
        return match.group(1)
    return value.strip()


class OperatorParserProfileAssignments(BaseModel):
    clients: dict[str, str] = Field(default_factory=dict)
    source_containers: dict[str, str] = Field(default_factory=dict)


class ReactionFeedbackMeaning(BaseModel):
    label: str
    prompt_hint: str
    score: int | None = None

    @field_validator("score")
    @classmethod
    def _validate_score(cls, value: int | None) -> int | None:
        if value is not None and not 1 <= value <= 5:
            raise ValueError("reaction feedback score must be between 1 and 5")
        return value


class Settings(BaseSettings):
    DATABASE_URL: str
    REDIS_URL: str
    ANTHROPIC_API_KEY: str
    OPENAI_API_KEY: str
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REFRESH_TOKEN: str = ""
    GOOGLE_SERVICE_ACCOUNT_FILE: str = ""
    GOOGLE_API_TIMEOUT_SECONDS: int = Field(default=60, gt=0)
    GOOGLE_DOC_ID: str
    GOOGLE_DOC_IDS: Annotated[list[str], NoDecode] = Field(default_factory=list)
    GOOGLE_OWNER_EMAIL: str = ""  # Google account to share bot-created docs with
    SECRET_KEY: str
    ENV: str
    BUILD_SHA: str = "unknown"
    RUNTIME_STATE_FILE: str = ""
    AUTO_SYNC_ENABLED: bool = False
    AUTO_SYNC_INTERVAL_SECONDS: int = Field(default=300, gt=0)

    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_ALLOWED_CHAT_ID: int = 0
    TELEGRAM_MINI_APP_URL: str = ""
    TELEGRAM_WEBAPP_AUTH_MAX_AGE_SECONDS: int = Field(default=86_400, gt=0)
    TELEGRAM_NUMERIC_FEEDBACK_ENABLED: bool = False
    TELEGRAM_REACTION_FEEDBACK_MAPPING: dict[str, ReactionFeedbackMeaning] = Field(
        default_factory=dict
    )
    VOICE_MEDIA_DIR: str = "/tmp/dream_voice"
    VOICE_RETENTION_SECONDS: int = Field(default=3600, ge=0)
    VOICE_TRANSCRIPT_RETENTION_SECONDS: int = Field(default=604_800, ge=0)
    APP_TIMEZONE: str = "Asia/Tbilisi"

    EMBEDDING_MODEL: str = "text-embedding-3-small"
    RETRIEVAL_THRESHOLD: float = 0.20
    BULK_CONFIRM_TOKEN_TTL_SECONDS: int = Field(default=600, gt=0)

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

    @model_validator(mode="after")
    def _validate_research_api_key_when_enabled(self) -> "Settings":
        if self.RESEARCH_AUGMENTATION_ENABLED and not self.RESEARCH_API_KEY.strip():
            raise ValueError("RESEARCH_API_KEY must be set when RESEARCH_AUGMENTATION_ENABLED=True")
        return self

    @model_validator(mode="after")
    def _validate_secret_key(self) -> "Settings":
        secret_key = self.SECRET_KEY.strip()
        if not secret_key:
            raise ValueError("SECRET_KEY must not be blank")

        if self.ENV.strip().lower() not in _TEST_ENVIRONMENTS:
            if len(secret_key.encode("utf-8")) < _MIN_SECRET_KEY_BYTES:
                raise ValueError(
                    f"SECRET_KEY must be at least {_MIN_SECRET_KEY_BYTES} bytes outside tests"
                )
            if len(set(secret_key)) < _MIN_SECRET_KEY_UNIQUE_CHARACTERS:
                raise ValueError("SECRET_KEY does not have enough character diversity")
            if any(marker in secret_key.lower() for marker in _DISALLOWED_SECRET_KEY_MARKERS):
                raise ValueError("SECRET_KEY must not be a placeholder value")
        return self

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

# doc_id -> human-readable name; loaded from file + updated at runtime
_doc_names: dict[str, str] = {}


def get_effective_google_doc_id() -> str:
    """Return the currently active GOOGLE_DOC_ID (runtime override takes precedence)."""
    persisted_doc_id = _load_persisted_primary_doc_id()
    if persisted_doc_id:
        return persisted_doc_id
    if _google_doc_id_override is not None:
        return _google_doc_id_override
    return get_settings().GOOGLE_DOC_ID


def set_google_doc_id_override(doc_id: str) -> None:
    """Override GOOGLE_DOC_ID at runtime without restarting the process."""
    global _google_doc_id_override
    _google_doc_id_override = doc_id
    _persist_extra_docs(primary_override=doc_id)


def set_google_doc_ids_override(doc_ids: list[str]) -> None:
    global _google_doc_ids_override
    _google_doc_ids_override = doc_ids
    _persist_extra_docs(extras_override=doc_ids)


def register_doc_name(doc_id: str, name: str) -> None:
    """Store a human-readable name for *doc_id* and persist it."""
    _doc_names[doc_id] = name
    _persist_extra_docs(name_updates={doc_id: name})


def get_doc_name(doc_id: str) -> str:
    """Return the stored name for *doc_id*, or a short fallback."""
    _ensure_names_loaded()
    return _doc_names.get(doc_id) or f"…{doc_id[-8:]}"


def _ensure_names_loaded() -> None:
    # Multiple services share this file.  Refresh on every lookup so a name
    # registered by auto-sync is visible to the already-running bot/API.
    for doc_id, name in _load_doc_names().items():
        _doc_names[doc_id] = name
    for entry in _load_extra_docs_raw():
        if isinstance(entry, dict) and entry.get("id"):
            _doc_names[entry["id"]] = entry.get("name") or entry["id"]


def _persist_extra_docs(
    *,
    primary_override: str | None = None,
    extras_override: list[str] | None = None,
    name_updates: dict[str, str] | None = None,
) -> None:
    with _runtime_state_lock:
        state_file = _runtime_state_file()
        try:
            with _runtime_file_lock(state_file, exclusive=True):
                persisted = _read_runtime_docs_payload_unlocked(state_file)
                primary = (
                    primary_override
                    or _payload_primary(persisted)
                    or _google_doc_id_override
                    or get_settings().GOOGLE_DOC_ID
                )

                if extras_override is not None:
                    configured_extras = extras_override
                elif "extras" in persisted:
                    configured_extras = _extra_doc_ids_from_payload(persisted)
                elif _google_doc_ids_override is not None:
                    configured_extras = _google_doc_ids_override
                else:
                    configured_extras = get_settings().GOOGLE_DOC_IDS

                candidates: list[str] = []
                settings_primary = get_settings().GOOGLE_DOC_ID
                if settings_primary and settings_primary != primary:
                    candidates.append(settings_primary)
                candidates.extend(configured_extras)
                extras_ids = _dedupe_doc_ids(candidates, exclude={primary})

                names = _doc_names_from_payload(persisted)
                for key, value in _doc_names.items():
                    if key and value:
                        names.setdefault(key, value)
                names.update(
                    {key: value for key, value in (name_updates or {}).items() if key and value}
                )
                entries = [
                    {"id": doc_id, "name": names.get(doc_id, doc_id)} for doc_id in extras_ids
                ]
                payload = {
                    "primary": primary,
                    "extras": entries,
                    "names": names,
                }
                _atomic_write_json(state_file, payload)
        except Exception:
            _logger.warning("Failed to persist extra docs to %s", state_file, exc_info=True)


@contextmanager
def _runtime_file_lock(path: Path, *, exclusive: bool) -> Iterator[None]:
    """Coordinate runtime-state reads/writes across bot, API and auto-sync."""

    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f"{path.name}.lock")
    with lock_path.open("a+b") as stream:
        if fcntl is not None:
            operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
            fcntl.flock(stream.fileno(), operation)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    """Durably replace runtime state without exposing a partial JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
        try:
            directory_descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        except (AttributeError, OSError):
            return
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def _load_runtime_docs_payload() -> dict[str, object]:
    state_file = _runtime_state_file()
    try:
        with _runtime_state_lock:
            with _runtime_file_lock(state_file, exclusive=False):
                return _read_runtime_docs_payload_unlocked(state_file)
    except Exception:
        _logger.warning("Failed to load extra docs from %s", state_file, exc_info=True)
    return {}


def _read_runtime_docs_payload_unlocked(state_file: Path) -> dict[str, object]:
    if not state_file.exists():
        return {}
    data = json.loads(state_file.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return data
    if isinstance(data, list):
        return {"extras": data}
    return {}


def _runtime_state_file() -> Path:
    configured = get_settings().RUNTIME_STATE_FILE.strip()
    return Path(configured) if configured else _EXTRA_DOCS_FILE


def _load_extra_docs_raw() -> list[object]:
    data = _load_runtime_docs_payload()
    extras = data.get("extras")
    if isinstance(extras, list):
        return extras
    return []


def _load_doc_names() -> dict[str, str]:
    return _doc_names_from_payload(_load_runtime_docs_payload())


def _doc_names_from_payload(data: dict[str, object]) -> dict[str, str]:
    names = data.get("names")
    result = (
        {
            str(doc_id): str(name)
            for doc_id, name in names.items()
            if isinstance(doc_id, str) and doc_id and isinstance(name, str) and name
        }
        if isinstance(names, dict)
        else {}
    )
    extras = data.get("extras")
    for entry in extras if isinstance(extras, list) else []:
        if isinstance(entry, dict):
            doc_id = entry.get("id")
            name = entry.get("name")
            if isinstance(doc_id, str) and doc_id and isinstance(name, str) and name:
                result[doc_id] = name
    return result


def _load_persisted_primary_doc_id() -> str | None:
    return _payload_primary(_load_runtime_docs_payload())


def _payload_primary(data: dict[str, object]) -> str | None:
    primary = data.get("primary")
    if isinstance(primary, str) and primary.strip():
        return primary.strip()
    return None


def _extra_doc_ids_from_payload(data: dict[str, object]) -> list[str]:
    ids: list[str] = []
    extras = data.get("extras")
    if not isinstance(extras, list):
        return ids
    for entry in extras:
        if isinstance(entry, dict):
            doc_id = entry.get("id")
            if doc_id:
                ids.append(str(doc_id))
                if entry.get("name"):
                    _doc_names[str(doc_id)] = str(entry["name"])
        elif isinstance(entry, str) and entry:
            ids.append(entry)
    return ids


def _dedupe_doc_ids(doc_ids: list[str], *, exclude: set[str] | None = None) -> list[str]:
    seen = set(exclude or set())
    result: list[str] = []
    for doc_id in doc_ids:
        if doc_id and doc_id not in seen:
            seen.add(doc_id)
            result.append(doc_id)
    return result


def get_all_doc_ids() -> list[str]:
    persisted = _load_runtime_docs_payload()
    primary = _payload_primary(persisted) or _google_doc_id_override or get_settings().GOOGLE_DOC_ID
    if "extras" in persisted:
        extras = _extra_doc_ids_from_payload(persisted)
    elif _google_doc_ids_override is not None:
        extras = _google_doc_ids_override
    else:
        extras = get_settings().GOOGLE_DOC_IDS
    settings_primary = get_settings().GOOGLE_DOC_ID
    candidates = [settings_primary] if settings_primary != primary else []
    candidates.extend(extras)
    return [primary, *_dedupe_doc_ids(candidates, exclude={primary})]


def _source_container_from_path(source_path: str) -> str | None:
    normalized_path = source_path.strip("/")
    if not normalized_path or "/" not in normalized_path:
        return None
    return normalized_path.rsplit("/", 1)[0]

from functools import lru_cache
from typing import Annotated

from pydantic import BaseModel
from pydantic import Field
from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


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
            return v
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


def get_all_doc_ids() -> list[str]:
    primary = get_effective_google_doc_id()
    extras = (
        _google_doc_ids_override
        if _google_doc_ids_override is not None
        else get_settings().GOOGLE_DOC_IDS
    )
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

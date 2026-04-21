from functools import lru_cache

from pydantic import BaseModel
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    SECRET_KEY: str
    ENV: str

    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_ALLOWED_CHAT_ID: int = 0
    VOICE_MEDIA_DIR: str = "/tmp/dream_voice"
    VOICE_RETENTION_SECONDS: int = 3600

    EMBEDDING_MODEL: str = "text-embedding-3-small"
    RETRIEVAL_THRESHOLD: float = 0.35
    MAX_INDEX_AGE_HOURS: int = 24
    BULK_CONFIRM_TOKEN_TTL_SECONDS: int = 600

    # Feature flags are evaluated once per process because get_settings() is lru-cached.
    MOTIF_INDUCTION_ENABLED: bool = False
    RESEARCH_API_BASE_URL: str = "https://api.tavily.com"
    RESEARCH_API_KEY: str = ""
    RESEARCH_AUGMENTATION_ENABLED: bool = False
    OPERATOR_PARSER_PROFILE_ASSIGNMENTS: OperatorParserProfileAssignments = Field(
        default_factory=OperatorParserProfileAssignments
    )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

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


def _source_container_from_path(source_path: str) -> str | None:
    normalized_path = source_path.strip("/")
    if not normalized_path or "/" not in normalized_path:
        return None
    return normalized_path.rsplit("/", 1)[0]

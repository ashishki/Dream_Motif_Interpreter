from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


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

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

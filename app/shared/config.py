from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str
    REDIS_URL: str
    ANTHROPIC_API_KEY: str
    OPENAI_API_KEY: str
    GOOGLE_CLIENT_ID: str
    GOOGLE_CLIENT_SECRET: str
    GOOGLE_REFRESH_TOKEN: str
    GOOGLE_DOC_ID: str
    SECRET_KEY: str
    ENV: str

    EMBEDDING_MODEL: str = "text-embedding-3-small"
    RETRIEVAL_THRESHOLD: float = 0.35
    MAX_INDEX_AGE_HOURS: int = 24

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

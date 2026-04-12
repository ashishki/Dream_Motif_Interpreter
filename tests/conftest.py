import pytest


REQUIRED_ENV_VARS = {
    "DATABASE_URL": "postgresql+asyncpg://test:test@localhost:5432/test_db",
    "REDIS_URL": "redis://localhost:6379/0",
    "ANTHROPIC_API_KEY": "test-anthropic-key",
    "OPENAI_API_KEY": "test-openai-key",
    "GOOGLE_CLIENT_ID": "test-google-client-id",
    "GOOGLE_CLIENT_SECRET": "test-google-client-secret",
    "GOOGLE_REFRESH_TOKEN": "test-google-refresh-token",
    "GOOGLE_DOC_ID": "test-google-doc-id",
    "SECRET_KEY": "test-secret-key",
    "ENV": "test",
}


@pytest.fixture(autouse=True)
def _set_required_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in REQUIRED_ENV_VARS.items():
        monkeypatch.setenv(key, value)

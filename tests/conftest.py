import os

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.shared.config import get_settings


# ── env vars for all tests ──────────────────────────────────────────────────

# Real test DB (PostgreSQL on port 5433, created by env setup)
_TEST_DB_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres@localhost:5433/dream_motif_test",
)

REQUIRED_ENV_VARS = {
    "DATABASE_URL": _TEST_DB_URL,
    "REDIS_URL": "redis://localhost:6379/0",
    "ANTHROPIC_API_KEY": "test-anthropic-key",
    "OPENAI_API_KEY": "test-openai-key",
    "GOOGLE_CLIENT_ID": "test-google-client-id",
    "GOOGLE_CLIENT_SECRET": "test-google-client-secret",
    "GOOGLE_REFRESH_TOKEN": "test-google-refresh-token",
    "GOOGLE_DOC_ID": "test-google-doc-id",
    "SECRET_KEY": "test-secret-key-32-bytes-minimum-xx",
    "ENV": "test",
}


@pytest.fixture(autouse=True)
def _set_required_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in REQUIRED_ENV_VARS.items():
        monkeypatch.setenv(key, value)


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    yield
    get_settings.cache_clear()


# ── DB engine fixture for integration tests ─────────────────────────────────


@pytest_asyncio.fixture(scope="session")
async def db_engine() -> AsyncEngine:
    """Async SQLAlchemy engine connected to the test database."""
    engine = create_async_engine(_TEST_DB_URL, echo=False)
    yield engine
    await engine.dispose()

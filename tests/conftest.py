import os

import pytest
import pytest_asyncio
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.shared.config import get_settings


# ── env vars for all tests ──────────────────────────────────────────────────


# Real test DB (PostgreSQL on port 5433, created by env setup)
def _validated_test_database_url(value: str) -> str:
    """Fail collection before any integration fixture can drop a real schema."""
    try:
        parsed = make_url(value)
    except Exception as exc:
        raise RuntimeError("TEST_DATABASE_URL is not a valid SQLAlchemy URL") from exc
    if parsed.get_backend_name() != "postgresql":
        raise RuntimeError("TEST_DATABASE_URL must point to PostgreSQL")
    database_name = (parsed.database or "").casefold()
    if not database_name.endswith(("_test", "_testing", "_eval")):
        raise RuntimeError(
            "Refusing destructive integration tests: TEST_DATABASE_URL database "
            "name must end in _test, _testing, or _eval"
        )
    return value


_TEST_DB_URL = _validated_test_database_url(
    os.getenv(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://postgres@localhost:5433/dream_motif_test",
    )
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

GDOCS_ENV_VARS = {
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "GOOGLE_REFRESH_TOKEN",
    "GOOGLE_SERVICE_ACCOUNT_FILE",
    "GOOGLE_DOC_ID",
}
OPENAI_ENV_VARS = {"OPENAI_API_KEY"}


@pytest.fixture(autouse=True)
def _set_required_env_vars(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    preserve_gdocs_env = request.node.get_closest_marker("preserve_gdocs_env") is not None
    preserve_openai_env = request.node.get_closest_marker("preserve_openai_env") is not None
    for key, value in REQUIRED_ENV_VARS.items():
        if preserve_gdocs_env and key in GDOCS_ENV_VARS:
            continue
        if preserve_openai_env and key in OPENAI_ENV_VARS:
            continue
        monkeypatch.setenv(key, value)


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _clear_ephemeral_assistant_state() -> None:
    from app.assistant import session as session_module

    session_module._recent_dream_sets.clear()
    session_module._displayed_dream_sets.clear()
    session_module._pending_batch_dream_notes.clear()
    session_module._pending_single_dream_notes.clear()
    yield
    session_module._recent_dream_sets.clear()
    session_module._displayed_dream_sets.clear()
    session_module._pending_batch_dream_notes.clear()
    session_module._pending_single_dream_notes.clear()


# ── DB engine fixture for integration tests ─────────────────────────────────


@pytest_asyncio.fixture(scope="session")
async def db_engine() -> AsyncEngine:
    """Async SQLAlchemy engine connected to the test database."""
    engine = create_async_engine(_TEST_DB_URL, echo=False)
    yield engine
    await engine.dispose()

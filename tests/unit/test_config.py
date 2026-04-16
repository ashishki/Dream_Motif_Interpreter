from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.shared.config import Settings

REQUIRED_SECRET_VARS = (
    "DATABASE_URL",
    "REDIS_URL",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "GOOGLE_REFRESH_TOKEN",
    "GOOGLE_DOC_ID",
    "SECRET_KEY",
)


def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/dmi")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("GOOGLE_REFRESH_TOKEN", "test-refresh-token")
    monkeypatch.setenv("GOOGLE_DOC_ID", "test-doc-id")
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("ENV", "test")


def test_motif_induction_enabled_defaults_to_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.delenv("MOTIF_INDUCTION_ENABLED", raising=False)

    settings = Settings()

    assert settings.MOTIF_INDUCTION_ENABLED is False


@pytest.mark.parametrize("missing_var", REQUIRED_SECRET_VARS)
def test_config_fails_fast_on_missing_required_secret(
    monkeypatch: pytest.MonkeyPatch,
    missing_var: str,
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.delenv(missing_var, raising=False)

    with pytest.raises(ValidationError):
        Settings()

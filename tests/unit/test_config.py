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


@pytest.mark.parametrize("missing_var", REQUIRED_SECRET_VARS)
def test_config_fails_fast_on_missing_required_secret(
    monkeypatch: pytest.MonkeyPatch,
    missing_var: str,
) -> None:
    monkeypatch.delenv(missing_var, raising=False)

    with pytest.raises(ValidationError):
        Settings()

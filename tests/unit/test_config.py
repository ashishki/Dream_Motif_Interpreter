from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.shared import config as config_module
from app.shared.config import Settings

REQUIRED_SECRET_VARS = (
    "DATABASE_URL",
    "REDIS_URL",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
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
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_FILE", raising=False)
    monkeypatch.setenv("GOOGLE_DOC_ID", "test-doc-id")
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("ENV", "test")


def test_motif_induction_enabled_defaults_to_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.delenv("MOTIF_INDUCTION_ENABLED", raising=False)

    settings = Settings(_env_file=None)

    assert settings.MOTIF_INDUCTION_ENABLED is True


@pytest.mark.parametrize("missing_var", REQUIRED_SECRET_VARS)
def test_config_fails_fast_on_missing_required_secret(
    monkeypatch: pytest.MonkeyPatch,
    missing_var: str,
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.delenv(missing_var, raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_config_allows_service_account_file_without_oauth_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/dmi")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_FILE", "/tmp/service-account.json")
    monkeypatch.setenv("GOOGLE_DOC_ID", "test-doc-id")
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("ENV", "test")
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("GOOGLE_REFRESH_TOKEN", raising=False)

    settings = Settings(_env_file=None)

    assert settings.GOOGLE_SERVICE_ACCOUNT_FILE == "/tmp/service-account.json"
    assert settings.GOOGLE_CLIENT_ID == ""
    assert settings.GOOGLE_CLIENT_SECRET == ""
    assert settings.GOOGLE_REFRESH_TOKEN == ""


def test_operator_parser_profile_assignments_parse_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv(
        "OPERATOR_PARSER_PROFILE_ASSIGNMENTS",
        '{"clients":{"client-a":"heading_based"},"source_containers":{"folders/april":"dated_entries"}}',
    )

    settings = Settings(_env_file=None)

    assert (
        settings.resolve_operator_parser_profile(
            client_id="client-a",
            source_path="folders/april/doc-1",
        )
        == "heading_based"
    )
    assert (
        settings.resolve_operator_parser_profile(
            client_id="client-b",
            source_path="folders/april/doc-2",
        )
        == "dated_entries"
    )


def test_get_effective_google_doc_id_prefers_runtime_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    config_module.get_settings.cache_clear()
    config_module._google_doc_id_override = None
    config_module.set_google_doc_id_override("runtime-doc-id")

    try:
        assert config_module.get_effective_google_doc_id() == "runtime-doc-id"
    finally:
        config_module._google_doc_id_override = None
        config_module.get_settings.cache_clear()


def test_get_effective_google_doc_id_falls_back_to_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    config_module.get_settings.cache_clear()
    config_module._google_doc_id_override = None

    try:
        assert config_module.get_effective_google_doc_id() == "test-doc-id"
    finally:
        config_module._google_doc_id_override = None
        config_module.get_settings.cache_clear()


def test_google_doc_ids_parse_from_env_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("GOOGLE_DOC_IDS", "doc-b, doc-c ,,")

    settings = Settings(_env_file=None)

    assert settings.GOOGLE_DOC_IDS == ["doc-b", "doc-c"]


def test_get_all_doc_ids_primary_first_and_deduplicated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("GOOGLE_DOC_IDS", "doc-b,doc-c")
    config_module.get_settings.cache_clear()
    config_module._google_doc_id_override = None
    config_module._google_doc_ids_override = None

    try:
        assert config_module.get_all_doc_ids() == ["test-doc-id", "doc-b", "doc-c"]
        config_module._google_doc_ids_override = ["test-doc-id", "doc-b"]
        assert config_module.get_all_doc_ids() == ["test-doc-id", "doc-b"]
    finally:
        config_module._google_doc_id_override = None
        config_module._google_doc_ids_override = None
        config_module.get_settings.cache_clear()

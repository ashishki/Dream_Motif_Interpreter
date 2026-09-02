from __future__ import annotations

import json

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


@pytest.fixture(autouse=True)
def isolate_runtime_google_docs_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(config_module, "_EXTRA_DOCS_FILE", tmp_path / "runtime_extra_docs.json")
    config_module._google_doc_id_override = None
    config_module._google_doc_ids_override = None
    config_module._doc_names.clear()
    config_module.get_settings.cache_clear()
    yield
    config_module._google_doc_id_override = None
    config_module._google_doc_ids_override = None
    config_module._doc_names.clear()
    config_module.get_settings.cache_clear()


def test_motif_induction_enabled_defaults_to_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.delenv("MOTIF_INDUCTION_ENABLED", raising=False)

    settings = Settings(_env_file=None)

    assert settings.MOTIF_INDUCTION_ENABLED is True


def test_telegram_numeric_feedback_defaults_to_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.delenv("TELEGRAM_NUMERIC_FEEDBACK_ENABLED", raising=False)

    settings = Settings(_env_file=None)

    assert settings.TELEGRAM_NUMERIC_FEEDBACK_ENABLED is False


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


def test_get_effective_google_doc_id_uses_persisted_primary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("GOOGLE_DOC_IDS", "")
    config_module._EXTRA_DOCS_FILE.write_text(
        json.dumps(
            {
                "primary": "runtime-primary-doc",
                "extras": [{"id": "other-doc", "name": "Other doc"}],
            }
        ),
        encoding="utf-8",
    )
    config_module.get_settings.cache_clear()

    assert config_module.get_effective_google_doc_id() == "runtime-primary-doc"


def test_set_google_doc_id_override_persists_runtime_primary_and_existing_extras(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("GOOGLE_DOC_IDS", "")
    config_module._EXTRA_DOCS_FILE.write_text(
        json.dumps(
            [
                {"id": "runtime-primary-doc", "name": "Runtime primary"},
                {"id": "other-doc", "name": "Other doc"},
            ]
        ),
        encoding="utf-8",
    )
    config_module.get_settings.cache_clear()

    config_module.set_google_doc_id_override("runtime-primary-doc")

    payload = json.loads(config_module._EXTRA_DOCS_FILE.read_text(encoding="utf-8"))
    assert payload["primary"] == "runtime-primary-doc"
    assert [entry["id"] for entry in payload["extras"]] == ["test-doc-id", "other-doc"]


def test_runtime_state_file_can_live_on_a_persistent_volume(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _set_required_env(monkeypatch)
    state_file = tmp_path / "persistent" / "runtime-state.json"
    monkeypatch.setenv("RUNTIME_STATE_FILE", str(state_file))
    config_module.get_settings.cache_clear()

    config_module.set_google_doc_id_override("persistent-primary-doc")

    payload = json.loads(state_file.read_text(encoding="utf-8"))
    assert payload["primary"] == "persistent-primary-doc"


def test_runtime_state_atomic_replace_failure_preserves_previous_json(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _set_required_env(monkeypatch)
    state_file = tmp_path / "persistent" / "runtime-state.json"
    state_file.parent.mkdir(parents=True)
    original = '{"primary":"known-good","extras":[]}'
    state_file.write_text(original, encoding="utf-8")
    monkeypatch.setenv("RUNTIME_STATE_FILE", str(state_file))
    config_module.get_settings.cache_clear()

    monkeypatch.setattr(
        config_module.os,
        "replace",
        lambda *_args: (_ for _ in ()).throw(OSError("simulated crash")),
    )
    config_module.set_google_doc_id_override("new-primary")

    assert state_file.read_text(encoding="utf-8") == original
    assert list(state_file.parent.glob("*.tmp")) == []


def test_runtime_extra_docs_override_survives_process_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("GOOGLE_DOC_IDS", "env-doc")
    config_module.get_settings.cache_clear()

    config_module.set_google_doc_ids_override(["runtime-doc"])

    # A different/restarted process has no in-memory override.  The shared
    # state file remains authoritative over the startup environment.
    config_module._google_doc_ids_override = None
    assert config_module.get_all_doc_ids() == ["test-doc-id", "runtime-doc"]


def test_runtime_state_update_merges_fresh_cross_process_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("GOOGLE_DOC_IDS", "")
    config_module.get_settings.cache_clear()
    config_module._google_doc_id_override = "stale-local-primary"
    config_module._google_doc_ids_override = ["stale-local-extra"]
    config_module._doc_names["local-doc"] = "Local name"
    config_module._doc_names["fresh-extra"] = "Stale name"
    config_module._EXTRA_DOCS_FILE.write_text(
        json.dumps(
            {
                "primary": "fresh-primary",
                "extras": [{"id": "fresh-extra", "name": "Fresh extra"}],
                "names": {"fresh-primary": "Fresh primary"},
            }
        ),
        encoding="utf-8",
    )

    config_module.register_doc_name("new-doc", "New name")

    payload = json.loads(config_module._EXTRA_DOCS_FILE.read_text(encoding="utf-8"))
    assert payload["primary"] == "fresh-primary"
    assert [item["id"] for item in payload["extras"]] == ["test-doc-id", "fresh-extra"]
    assert payload["names"] == {
        "fresh-primary": "Fresh primary",
        "fresh-extra": "Fresh extra",
        "local-doc": "Local name",
        "new-doc": "New name",
    }


def test_doc_name_refreshes_after_another_process_updates_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    config_module.get_settings.cache_clear()

    assert config_module.get_doc_name("shared-doc") == "…ared-doc"
    config_module._EXTRA_DOCS_FILE.write_text(
        json.dumps({"primary": "test-doc-id", "extras": [], "names": {"shared-doc": "Shared"}}),
        encoding="utf-8",
    )

    assert config_module.get_doc_name("shared-doc") == "Shared"


def test_google_doc_ids_parse_from_env_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("GOOGLE_DOC_IDS", "doc-b, doc-c ,,")

    settings = Settings(_env_file=None)

    assert settings.GOOGLE_DOC_IDS == ["doc-b", "doc-c"]


def test_research_api_key_required_when_research_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("RESEARCH_AUGMENTATION_ENABLED", "true")
    monkeypatch.setenv("RESEARCH_API_KEY", "")

    with pytest.raises(ValidationError, match="RESEARCH_API_KEY must be set"):
        Settings(_env_file=None)


def test_research_api_key_can_be_empty_when_research_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("RESEARCH_AUGMENTATION_ENABLED", "false")
    monkeypatch.setenv("RESEARCH_API_KEY", "")

    settings = Settings(_env_file=None)

    assert settings.RESEARCH_API_KEY == ""


def test_config_rejects_blank_secret_key_even_in_tests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("SECRET_KEY", "   ")

    with pytest.raises(ValidationError, match="SECRET_KEY must not be blank"):
        Settings(_env_file=None)


@pytest.mark.parametrize(
    "secret_key",
    ["short-secret", "a" * 64, "test-secret-key-32-bytes-minimum-xx"],
)
def test_config_rejects_weak_secret_key_outside_tests(
    monkeypatch: pytest.MonkeyPatch,
    secret_key: str,
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("SECRET_KEY", secret_key)

    with pytest.raises(ValidationError, match="SECRET_KEY"):
        Settings(_env_file=None)


def test_config_accepts_strong_secret_key_outside_tests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "fC1wR9-Qk7vL2xP8sN4mT6yH3aB5dE0z")
    monkeypatch.delenv("BUILD_SHA", raising=False)

    settings = Settings(_env_file=None)

    assert settings.BUILD_SHA == "unknown"


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("AUTO_SYNC_INTERVAL_SECONDS", "0"),
        ("TELEGRAM_WEBAPP_AUTH_MAX_AGE_SECONDS", "0"),
        ("GOOGLE_API_TIMEOUT_SECONDS", "0"),
        ("VOICE_RETENTION_SECONDS", "-1"),
        ("VOICE_TRANSCRIPT_RETENTION_SECONDS", "-1"),
        ("BULK_CONFIRM_TOKEN_TTL_SECONDS", "0"),
    ],
)
def test_config_rejects_unsafe_non_positive_operational_windows(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


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


def test_get_all_doc_ids_accepts_legacy_runtime_extra_docs_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("GOOGLE_DOC_IDS", "")
    config_module._EXTRA_DOCS_FILE.write_text(
        json.dumps([{"id": "legacy-extra-doc", "name": "Legacy"}]),
        encoding="utf-8",
    )
    config_module.get_settings.cache_clear()

    assert config_module.get_all_doc_ids() == ["test-doc-id", "legacy-extra-doc"]


def test_get_all_doc_ids_keeps_settings_primary_when_runtime_primary_differs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("GOOGLE_DOC_IDS", "")
    config_module._EXTRA_DOCS_FILE.write_text(
        json.dumps(
            {
                "primary": "runtime-primary-doc",
                "extras": [{"id": "other-doc", "name": "Other"}],
            }
        ),
        encoding="utf-8",
    )
    config_module.get_settings.cache_clear()

    assert config_module.get_all_doc_ids() == [
        "runtime-primary-doc",
        "test-doc-id",
        "other-doc",
    ]

from __future__ import annotations

import hashlib
import hmac
import importlib
import json
import sys
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import quote

from app.shared.telegram_auth import is_valid_telegram_web_app_init_data


BOT_TOKEN = "123456:test-token"
ALLOWED_USER_ID = 42
NOW = 1_800_000_000


def test_telegram_webapp_init_data_accepts_valid_signed_user() -> None:
    init_data = _signed_init_data(
        {
            "auth_date": str(NOW),
            "query_id": "query-1",
            "user": json.dumps({"id": ALLOWED_USER_ID, "first_name": "A"}, separators=(",", ":")),
        }
    )

    assert is_valid_telegram_web_app_init_data(
        init_data,
        bot_token=BOT_TOKEN,
        allowed_user_id=ALLOWED_USER_ID,
        now=NOW,
    )


def test_telegram_webapp_init_data_rejects_tampered_payload() -> None:
    init_data = _signed_init_data(
        {
            "auth_date": str(NOW),
            "user": json.dumps({"id": ALLOWED_USER_ID}, separators=(",", ":")),
        }
    )

    assert not is_valid_telegram_web_app_init_data(
        init_data.replace(str(ALLOWED_USER_ID), "999"),
        bot_token=BOT_TOKEN,
        allowed_user_id=ALLOWED_USER_ID,
        now=NOW,
    )


def test_telegram_webapp_init_data_rejects_wrong_user_and_stale_auth_date() -> None:
    wrong_user = _signed_init_data(
        {
            "auth_date": str(NOW),
            "user": json.dumps({"id": 99}, separators=(",", ":")),
        }
    )
    stale = _signed_init_data(
        {
            "auth_date": str(NOW - 90_000),
            "user": json.dumps({"id": ALLOWED_USER_ID}, separators=(",", ":")),
        }
    )

    assert not is_valid_telegram_web_app_init_data(
        wrong_user,
        bot_token=BOT_TOKEN,
        allowed_user_id=ALLOWED_USER_ID,
        now=NOW,
    )
    assert not is_valid_telegram_web_app_init_data(
        stale,
        bot_token=BOT_TOKEN,
        allowed_user_id=ALLOWED_USER_ID,
        now=NOW,
        max_age_seconds=86_400,
    )


def test_main_auth_accepts_telegram_webapp_init_data_header() -> None:
    init_data = _signed_init_data(
        {
            "auth_date": str(NOW),
            "user": json.dumps({"id": ALLOWED_USER_ID}, separators=(",", ":")),
        }
    )
    settings = SimpleNamespace(
        TELEGRAM_BOT_TOKEN=BOT_TOKEN,
        TELEGRAM_ALLOWED_CHAT_ID=ALLOWED_USER_ID,
        TELEGRAM_WEBAPP_AUTH_MAX_AGE_SECONDS=86_400,
    )

    sys.modules.pop("app.main", None)
    from app.shared.config import get_settings

    get_settings.cache_clear()
    with (
        patch.dict(
            "os.environ",
            {
                "DATABASE_URL": "postgresql+asyncpg://user:pass@localhost/test",
                "REDIS_URL": "redis://localhost:6379/0",
                "ANTHROPIC_API_KEY": "test-anthropic",
                "OPENAI_API_KEY": "test-openai",
                "GOOGLE_DOC_ID": "test-doc",
                "SECRET_KEY": "test-secret",
                "ENV": "test",
            },
            clear=False,
        ),
    ):
        main_module = importlib.import_module("app.main")
    get_settings.cache_clear()

    with (
        patch.object(main_module, "is_valid_api_key", return_value=False),
        patch.object(main_module, "get_settings", return_value=settings),
        patch.object(
            main_module, "is_valid_telegram_web_app_init_data", return_value=True
        ) as validator,
    ):
        assert main_module._has_valid_auth_headers({"X-Telegram-Init-Data": init_data})

    validator.assert_called_once_with(
        init_data,
        bot_token=BOT_TOKEN,
        allowed_user_id=ALLOWED_USER_ID,
        max_age_seconds=86_400,
    )


def _signed_init_data(fields: dict[str, str]) -> str:
    data_check_string = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    payload = {
        **fields,
        "hash": hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest(),
    }
    return "&".join(f"{key}={quote(value)}" for key, value in payload.items())

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import Mapping
from urllib.parse import parse_qsl


def is_valid_telegram_web_app_init_data(
    init_data: str | None,
    *,
    bot_token: str,
    allowed_user_id: int,
    now: int | None = None,
    max_age_seconds: int = 86_400,
) -> bool:
    if not init_data or not bot_token or allowed_user_id == 0:
        return False

    fields = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = fields.pop("hash", None)
    if not received_hash:
        return False

    data_check_string = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected_hash = hmac.new(
        secret_key,
        data_check_string.encode(),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected_hash, received_hash):
        return False

    if not _auth_date_is_fresh(fields, now=now, max_age_seconds=max_age_seconds):
        return False

    return _init_data_user_id(fields) == allowed_user_id


def _auth_date_is_fresh(
    fields: Mapping[str, str],
    *,
    now: int | None,
    max_age_seconds: int,
) -> bool:
    try:
        auth_date = int(fields["auth_date"])
    except (KeyError, TypeError, ValueError):
        return False
    current_time = int(time.time()) if now is None else now
    return 0 <= current_time - auth_date <= max_age_seconds


def _init_data_user_id(fields: Mapping[str, str]) -> int | None:
    try:
        user = json.loads(fields["user"])
    except (KeyError, TypeError, json.JSONDecodeError):
        return None
    if not isinstance(user, dict):
        return None
    user_id = user.get("id")
    return user_id if isinstance(user_id, int) else None

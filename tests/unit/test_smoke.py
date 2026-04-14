import importlib
import sys

import pytest
from pydantic import ValidationError

from app.shared.config import Settings
from app.shared.tracing import get_tracer


def test_app_starts(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(app: object, host: str, port: int, reload: bool) -> None:
        captured["app"] = app
        captured["host"] = host
        captured["port"] = port
        captured["reload"] = reload

    monkeypatch.setattr("uvicorn.run", fake_run)
    sys.modules.pop("app.main", None)

    module = importlib.import_module("app.main")
    module.main()

    assert captured["app"] is module.app
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8000
    assert captured["reload"] is False


def test_config_fails_fast_on_missing_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ValidationError):
        Settings()


def test_tracer_singleton() -> None:
    first = get_tracer()
    second = get_tracer()

    assert first is second
    assert type(first) is type(second)

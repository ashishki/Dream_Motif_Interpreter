from __future__ import annotations

import importlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient


def _reload_app():
    sys.modules.pop("app.main", None)

    return importlib.import_module("app.main").app


def test_no_inline_tracer_instances() -> None:
    app_root = Path(__file__).resolve().parents[2] / "app"
    disallowed_tokens = (
        "TracerProvider(",
        "SimpleSpanProcessor(",
        "SpanExporter",
        "trace.get_tracer(",
        "_NoOpSpanExporter",
    )

    for source_path in app_root.rglob("*.py"):
        if source_path == app_root / "shared" / "tracing.py":
            continue

        source = source_path.read_text(encoding="utf-8")
        for token in disallowed_tokens:
            assert token not in source, f"{token} found in {source_path}"


@pytest.mark.anyio
async def test_log_fields_present_and_no_pii(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fresh_timestamp = datetime.now(timezone.utc) - timedelta(hours=1)

    async def _fake_fetch() -> datetime:
        return fresh_timestamp

    monkeypatch.setattr("app.api.health._fetch_index_last_updated", _fake_fetch)

    async with AsyncClient(
        transport=ASGITransport(app=_reload_app()),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 200

    captured = capsys.readouterr()
    log_lines = [
        json.loads(line)
        for line in (captured.out + "\n" + captured.err).splitlines()
        if line.strip().startswith("{")
    ]
    request_log = next(line for line in log_lines if line.get("event") == "request.completed")

    assert request_log["env"] == "test"
    assert request_log["service"] == "dream-motif-interpreter"
    assert request_log["path"] == "/health"
    assert request_log["trace_id"] is not None
    assert request_log["span_id"] is not None
    assert "raw_text" not in request_log
    assert "quiet dream used for health checks" not in json.dumps(request_log)

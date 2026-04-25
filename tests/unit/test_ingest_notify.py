from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.api.dreams import SYNC_NOTIFY_PREFIX, get_and_delete_sync_notify, set_sync_notify
from app.workers.ingest import _notify_sync_complete


@pytest.mark.asyncio
async def test_set_and_get_sync_notify() -> None:
    job_id = uuid4()
    redis_client = AsyncMock()
    redis_client.get.return_value = "12345"

    await set_sync_notify(redis_client, job_id, 12345)
    chat_id = await get_and_delete_sync_notify(redis_client, job_id)

    redis_client.set.assert_awaited_once_with(f"{SYNC_NOTIFY_PREFIX}{job_id}", "12345", ex=3600)
    redis_client.get.assert_awaited_once_with(f"{SYNC_NOTIFY_PREFIX}{job_id}")
    redis_client.delete.assert_awaited_once_with(f"{SYNC_NOTIFY_PREFIX}{job_id}")
    assert chat_id == 12345


@pytest.mark.asyncio
async def test_get_and_delete_returns_none_when_missing() -> None:
    job_id = uuid4()
    redis_client = AsyncMock()
    redis_client.get.return_value = None

    chat_id = await get_and_delete_sync_notify(redis_client, job_id)

    assert chat_id is None
    redis_client.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_notify_sync_complete_sends_message_on_success() -> None:
    job_id = uuid4()
    redis_client = AsyncMock()
    settings = SimpleNamespace(TELEGRAM_BOT_TOKEN="bot-token")
    response = MagicMock()
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.__aexit__.return_value = False
    client.post.return_value = response

    with (
        patch("app.workers.ingest.get_and_delete_sync_notify", AsyncMock(return_value=12345)),
        patch("app.workers.ingest.get_settings", return_value=settings),
        patch("app.workers.ingest.get_doc_name", return_value="Сны Николая"),
        patch("httpx.AsyncClient", return_value=client) as mock_async_client,
    ):
        await _notify_sync_complete(redis_client, job_id, count=3, doc_id="doc-123", error=None)

    mock_async_client.assert_called_once()
    client.post.assert_awaited_once_with(
        "https://api.telegram.org/botbot-token/sendMessage",
        json={
            "chat_id": 12345,
            "text": "Синхронизация завершена: Сны Николая. Добавлено 3 записей.",
        },
    )
    response.raise_for_status.assert_called_once_with()


@pytest.mark.asyncio
async def test_notify_sync_complete_silent_when_no_chat_id() -> None:
    job_id = uuid4()
    redis_client = AsyncMock()

    with (
        patch("app.workers.ingest.get_and_delete_sync_notify", AsyncMock(return_value=None)),
        patch("httpx.AsyncClient") as mock_async_client,
    ):
        await _notify_sync_complete(redis_client, job_id, count=0, doc_id="doc-123", error=None)

    mock_async_client.assert_not_called()


@pytest.mark.asyncio
async def test_notify_sync_complete_silent_when_no_bot_token() -> None:
    job_id = uuid4()
    redis_client = AsyncMock()
    settings = SimpleNamespace(TELEGRAM_BOT_TOKEN="")

    with (
        patch("app.workers.ingest.get_and_delete_sync_notify", AsyncMock(return_value=12345)),
        patch("app.workers.ingest.get_settings", return_value=settings),
        patch("httpx.AsyncClient") as mock_async_client,
    ):
        await _notify_sync_complete(redis_client, job_id, count=0, doc_id="doc-123", error=None)

    mock_async_client.assert_not_called()

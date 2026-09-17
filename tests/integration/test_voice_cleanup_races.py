from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.assistant.voice_media import (
    claim_voice_media_event,
    get_or_create_voice_media_event,
    store_voice_media_path,
)
from app.models.voice import VoiceMediaEvent
from app.workers.cleanup import cleanup_voice_media

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _alembic_config() -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    return config


@pytest_asyncio.fixture
async def voice_cleanup_session_factory() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with engine.begin() as connection:
        await connection.exec_driver_sql("DROP SCHEMA IF EXISTS public CASCADE")
        await connection.exec_driver_sql("CREATE SCHEMA public")
        await connection.exec_driver_sql("GRANT ALL ON SCHEMA public TO public")
    await asyncio.to_thread(command.upgrade, _alembic_config(), "head")

    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


class _GatedSessionContext:
    def __init__(
        self,
        context: Any,
        *,
        candidate_selected: asyncio.Event,
        resume_cleanup: asyncio.Event,
    ) -> None:
        self._context = context
        self._candidate_selected = candidate_selected
        self._resume_cleanup = resume_cleanup

    async def __aenter__(self) -> AsyncSession:
        self._candidate_selected.set()
        await self._resume_cleanup.wait()
        return await self._context.__aenter__()

    async def __aexit__(self, *args: object) -> object:
        return await self._context.__aexit__(*args)


class _GateAfterCandidateScan:
    """Pause cleanup just before its per-row compare-and-lock query."""

    def __init__(self, delegate: async_sessionmaker[AsyncSession]) -> None:
        self._delegate = delegate
        self._calls = 0
        self.candidate_selected = asyncio.Event()
        self.resume_cleanup = asyncio.Event()

    def __call__(self) -> Any:
        self._calls += 1
        context = self._delegate()
        if self._calls != 2:
            return context
        return _GatedSessionContext(
            context,
            candidate_selected=self.candidate_selected,
            resume_cleanup=self.resume_cleanup,
        )


async def _tracked_voice_event(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    path: Path,
    telegram_message_id: int,
) -> VoiceMediaEvent:
    event, created = await get_or_create_voice_media_event(
        session_factory,
        chat_id=99001,
        telegram_message_id=telegram_message_id,
        telegram_file_id=f"voice-{telegram_message_id}",
        duration_seconds=3,
    )
    assert created
    await store_voice_media_path(session_factory, event.id, str(path))
    async with session_factory() as session:
        stored = await session.get(VoiceMediaEvent, event.id)
        assert stored is not None
        return stored


@pytest.mark.asyncio
async def test_new_worker_lease_after_candidate_scan_prevents_unlink(
    voice_cleanup_session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    voice_path = tmp_path / "new-lease.ogg"
    voice_path.write_bytes(b"voice")
    event = await _tracked_voice_event(
        voice_cleanup_session_factory,
        path=voice_path,
        telegram_message_id=88001,
    )
    gated_factory = _GateAfterCandidateScan(voice_cleanup_session_factory)

    cleanup_task = asyncio.create_task(
        cleanup_voice_media(
            gated_factory,  # type: ignore[arg-type]
            retention_seconds=0,
            media_dir=str(tmp_path),
        )
    )
    await asyncio.wait_for(gated_factory.candidate_selected.wait(), timeout=2)
    claimed = await claim_voice_media_event(
        voice_cleanup_session_factory,
        event.id,
        lease_owner="new-worker",
        lease_seconds=60,
    )
    assert claimed is not None

    gated_factory.resume_cleanup.set()
    assert await asyncio.wait_for(cleanup_task, timeout=2) == 0
    assert voice_path.exists()

    async with voice_cleanup_session_factory() as session:
        stored_path = await session.scalar(
            select(VoiceMediaEvent.local_path).where(VoiceMediaEvent.id == event.id)
        )
    assert stored_path == str(voice_path)


@pytest.mark.asyncio
async def test_concurrent_cleanup_passes_unlink_and_clear_path_once(
    voice_cleanup_session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    voice_path = tmp_path / "cleanup-race.ogg"
    voice_path.write_bytes(b"voice")
    event = await _tracked_voice_event(
        voice_cleanup_session_factory,
        path=voice_path,
        telegram_message_id=88002,
    )
    unlink_count = 0
    original_unlink = os.unlink

    def counted_unlink(path: Path) -> None:
        nonlocal unlink_count
        unlink_count += 1
        original_unlink(path)

    with patch("app.workers.cleanup.os.unlink", side_effect=counted_unlink):
        counts = await asyncio.gather(
            cleanup_voice_media(
                voice_cleanup_session_factory,
                retention_seconds=0,
                media_dir=str(tmp_path),
            ),
            cleanup_voice_media(
                voice_cleanup_session_factory,
                retention_seconds=0,
                media_dir=str(tmp_path),
            ),
        )

    assert sorted(counts) == [0, 1]
    assert unlink_count == 1
    assert not voice_path.exists()
    async with voice_cleanup_session_factory() as session:
        stored_path = await session.scalar(
            select(VoiceMediaEvent.local_path).where(VoiceMediaEvent.id == event.id)
        )
    assert stored_path == ""

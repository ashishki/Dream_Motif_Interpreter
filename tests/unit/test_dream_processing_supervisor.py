from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.workers.dream_supervisor import (
    dream_processing_wake_handler,
    start_dream_processing_supervisor,
    stop_dream_processing_supervisor,
    wake_dream_processing_supervisor,
)


@pytest.mark.asyncio
async def test_supervisor_recovers_at_start_and_stops_cleanly() -> None:
    application = SimpleNamespace(bot_data={"session_factory": object(), "facade": object()})
    processed = asyncio.Event()

    async def _process(_ctx, *, limit: int) -> int:
        assert limit == 1
        processed.set()
        return 0

    with (
        patch(
            "app.workers.dream_supervisor.process_pending_dream_jobs",
            new=AsyncMock(side_effect=_process),
        ) as process,
        patch(
            "app.workers.dream_supervisor.process_pending_note_jobs",
            new=AsyncMock(return_value=0),
        ) as process_notes,
    ):
        task = start_dream_processing_supervisor(
            application,
            poll_interval_seconds=3600,
            batch_size=7,
        )
        await asyncio.wait_for(processed.wait(), timeout=1)
        await stop_dream_processing_supervisor(application)

    assert task.done()
    process.assert_awaited_once()
    process_notes.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_wake_requests_an_immediate_second_sweep() -> None:
    application = SimpleNamespace(bot_data={"session_factory": object(), "facade": object()})
    second_sweep = asyncio.Event()

    async def _process(_ctx, *, limit: int) -> int:
        del limit
        if process.await_count >= 2:
            second_sweep.set()
        return 0

    with (
        patch(
            "app.workers.dream_supervisor.process_pending_dream_jobs",
            new=AsyncMock(side_effect=_process),
        ) as process,
        patch(
            "app.workers.dream_supervisor.process_pending_note_jobs",
            new=AsyncMock(return_value=0),
        ),
    ):
        start_dream_processing_supervisor(application, poll_interval_seconds=3600)
        while process.await_count < 1:
            await asyncio.sleep(0)

        context = SimpleNamespace(application=application)
        await dream_processing_wake_handler(None, context)
        await asyncio.wait_for(second_sweep.wait(), timeout=1)
        await stop_dream_processing_supervisor(application)

    assert process.await_count == 2


@pytest.mark.asyncio
async def test_slow_dream_turn_does_not_delay_first_note_turn() -> None:
    application = SimpleNamespace(bot_data={"session_factory": object(), "facade": object()})
    dream_started = asyncio.Event()
    release_dream = asyncio.Event()
    note_started = asyncio.Event()

    async def _process_dreams(_ctx, *, limit: int) -> int:
        assert limit == 1
        dream_started.set()
        await release_dream.wait()
        return 0

    async def _process_notes(_ctx, *, limit: int) -> int:
        assert limit == 1
        note_started.set()
        return 0

    with (
        patch(
            "app.workers.dream_supervisor.process_pending_dream_jobs",
            new=AsyncMock(side_effect=_process_dreams),
        ),
        patch(
            "app.workers.dream_supervisor.process_pending_note_jobs",
            new=AsyncMock(side_effect=_process_notes),
        ) as process_notes,
    ):
        start_dream_processing_supervisor(
            application,
            poll_interval_seconds=3600,
            batch_size=3,
        )
        await asyncio.wait_for(dream_started.wait(), timeout=1)
        await asyncio.wait_for(note_started.wait(), timeout=1)
        release_dream.set()
        await stop_dream_processing_supervisor(application)

    process_notes.assert_awaited()


@pytest.mark.asyncio
async def test_stop_is_bounded_when_active_stage_never_returns() -> None:
    application = SimpleNamespace(bot_data={"session_factory": object(), "facade": object()})
    started = asyncio.Event()
    finalized = asyncio.Event()

    async def _stuck_process(_ctx, *, limit: int) -> int:
        del limit
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            finalized.set()

    with (
        patch(
            "app.workers.dream_supervisor.process_pending_dream_jobs",
            new=_stuck_process,
        ),
        patch(
            "app.workers.dream_supervisor.DREAM_SUPERVISOR_STOP_TIMEOUT_SECONDS",
            0.01,
        ),
    ):
        task = start_dream_processing_supervisor(application, poll_interval_seconds=3600)
        await started.wait()
        await asyncio.wait_for(stop_dream_processing_supervisor(application), timeout=0.2)

    assert task.cancelled()
    assert finalized.is_set()


def test_wake_without_running_supervisor_is_safe() -> None:
    application = SimpleNamespace(bot_data={})

    assert wake_dream_processing_supervisor(application) is False

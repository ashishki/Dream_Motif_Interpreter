"""Live recovery loop for durable post-capture dream processing jobs."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

from app.workers.dream_processing import process_pending_dream_jobs
from app.workers.note_processing import process_pending_note_jobs

LOGGER = logging.getLogger(__name__)

_TASK_KEY = "_dream_processing_supervisor_task"
_STOP_KEY = "_dream_processing_supervisor_stop"
_WAKE_KEY = "_dream_processing_supervisor_wake"
DREAM_SUPERVISOR_STOP_TIMEOUT_SECONDS = 10.0


def start_dream_processing_supervisor(
    application: Any,
    *,
    poll_interval_seconds: float = 5.0,
    batch_size: int = 20,
) -> asyncio.Task[Any]:
    """Start one startup/periodic outbox drain loop for this application."""
    bot_data = application.bot_data
    existing = bot_data.get(_TASK_KEY)
    if isinstance(existing, asyncio.Task) and not existing.done():
        return existing

    stop = asyncio.Event()
    wake = asyncio.Event()
    wake.set()  # Recover committed work immediately after process startup.
    task = asyncio.create_task(
        dream_processing_supervisor(
            application,
            stop=stop,
            wake=wake,
            poll_interval_seconds=poll_interval_seconds,
            batch_size=batch_size,
        )
    )
    bot_data[_STOP_KEY] = stop
    bot_data[_WAKE_KEY] = wake
    bot_data[_TASK_KEY] = task
    return task


def wake_dream_processing_supervisor(application: Any) -> bool:
    """Request an immediate sweep after an update may have captured a dream."""
    wake = application.bot_data.get(_WAKE_KEY)
    if not isinstance(wake, asyncio.Event):
        return False
    wake.set()
    return True


async def stop_dream_processing_supervisor(application: Any) -> None:
    """Stop the loop after its currently leased stage reaches a safe boundary."""
    bot_data = application.bot_data
    stop = bot_data.pop(_STOP_KEY, None)
    wake = bot_data.pop(_WAKE_KEY, None)
    task = bot_data.pop(_TASK_KEY, None)
    if isinstance(stop, asyncio.Event):
        stop.set()
    if isinstance(wake, asyncio.Event):
        wake.set()
    if isinstance(task, asyncio.Task):
        try:
            await asyncio.wait_for(
                asyncio.shield(task),
                timeout=DREAM_SUPERVISOR_STOP_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            LOGGER.warning("Cancelling dream processing supervisor after shutdown timeout")
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("Dream processing supervisor failed during shutdown")


async def dream_processing_supervisor(
    application: Any,
    *,
    stop: asyncio.Event,
    wake: asyncio.Event,
    poll_interval_seconds: float,
    batch_size: int,
) -> None:
    """Drain due jobs after wake-ups and periodically recover missed work."""
    bot_data = application.bot_data
    session_factory = bot_data.get("session_factory")
    facade = bot_data.get("facade")
    if session_factory is None or facade is None:
        LOGGER.error("Dream processing supervisor lacks runtime dependencies")
        return

    ctx = {
        "session_factory": session_factory,
        "assistant_facade": facade,
    }
    interval = max(0.1, poll_interval_seconds)
    limit = max(1, min(batch_size, 100))

    while not stop.is_set():
        wake.clear()
        batch_exhausted = True
        for _ in range(limit):
            if stop.is_set():
                batch_exhausted = False
                break
            # One concurrent claim per queue gives both workloads an immediate
            # turn even when a stage in the other queue is slow or continuously
            # backlogged.
            results = await asyncio.gather(
                process_pending_dream_jobs(ctx, limit=1),
                process_pending_note_jobs(ctx, limit=1),
                return_exceptions=True,
            )
            dream_completed = _completed_queue_turn(results[0], queue_name="Dream")
            note_completed = _completed_queue_turn(results[1], queue_name="Note")
            if dream_completed == 0 and note_completed == 0:
                batch_exhausted = False
                break

        if batch_exhausted:
            # Yield between full batches, then continue without the polling delay.
            await asyncio.sleep(0)
            continue

        try:
            await asyncio.wait_for(wake.wait(), timeout=interval)
        except TimeoutError:
            continue


def _completed_queue_turn(result: object, *, queue_name: str) -> int:
    if isinstance(result, asyncio.CancelledError):
        raise result
    if isinstance(result, BaseException):
        LOGGER.error(
            "%s processing recovery turn failed",
            queue_name,
            exc_info=(type(result), result, result.__traceback__),
        )
        return 0
    return int(result)


async def dream_processing_wake_handler(_update: Any, context: Any) -> None:
    """PTB handler in the final group: wake after any user update completes."""
    wake_dream_processing_supervisor(context.application)

"""Leased voice transcription, reply delivery, and live recovery supervisor."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import socket
import time
import uuid
from collections.abc import Awaitable, Coroutine, MutableMapping
from pathlib import Path
from typing import Any, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.assistant.chat import handle_chat_with_metadata
from app.assistant.facade import AssistantFacade
from app.assistant.session import HISTORY_TTL_SECONDS
from app.assistant.tools import _has_natural_dream_opening
from app.assistant.voice_media import (
    VoiceLeaseLost,
    claim_recoverable_voice_media_events,
    get_voice_media_event,
    mark_voice_reply_delivered,
    mark_voice_reply_failed,
    record_voice_delivery_failure,
    record_voice_transcription_failure,
    release_voice_media_lease,
    renew_voice_media_lease,
    store_voice_delivery_progress,
    store_voice_media_path,
    store_voice_reply_pending,
    store_voice_transcript,
    update_voice_media_event_status,
)
from app.shared.config import get_settings
from app.telegram.handlers import (
    _extract_direct_note_text,
    _format_create_dream_reply,
    _maybe_store_pending_dream,
    _split_telegram_text,
    _telegram_source_event_key,
)
from app.telegram.voice import download_voice_file_by_id
from app.workers.cleanup import (
    cleanup_orphan_voice_files,
    cleanup_voice_media,
    delete_local_voice_file,
    purge_expired_bot_sessions,
    purge_expired_voice_transcripts,
    resolve_voice_media_path,
)

LOGGER = logging.getLogger(__name__)

_WHISPER_MODEL = "whisper-1"
_TRANSCRIPTION_FAILED_MESSAGE = (
    "Не удалось расшифровать голосовое сообщение. Я ничего не добавил в архив. "
    "Отправьте сообщение ещё раз или пришлите его текстом."
)
_PROCESSING_FAILED_MESSAGE = (
    "Голосовое сообщение расшифровано, но завершить обработку не удалось. "
    "Текст сохранён для повторной попытки; можно ответить на исходное голосовое командой."
)
_INTERRUPTED_MESSAGE = (
    "Обработка голосового сообщения прервалась до сохранения аудио. Отправьте его ещё раз."
)
_VOICE_TASKS_KEY = "_transcription_tasks"
_VOICE_WORKER_ID_KEY = "_voice_worker_id"
_VOICE_SUPERVISOR_TASK_KEY = "_voice_maintenance_supervisor_task"
_VOICE_SUPERVISOR_STOP_KEY = "_voice_maintenance_supervisor_stop"
VOICE_LEASE_SECONDS = 300
_WHISPER_TIMEOUT_SECONDS = min(240.0, float(VOICE_LEASE_SECONDS))
_MAX_TRANSCRIPTION_ATTEMPTS = 3
_TRANSCRIPTION_RETRY_DELAYS_SECONDS = (5, 30, 120)
_DELIVERY_RETRY_DELAYS_SECONDS = (5, 15, 60, 300)
_DOWNLOAD_RETRY_SECONDS = 30
VOICE_SUPERVISOR_STOP_TIMEOUT_SECONDS = 5.0
VOICE_ACTIVE_TASK_STOP_TIMEOUT_SECONDS = 10.0

_T = TypeVar("_T")


def schedule_voice_task(
    bot_data: MutableMapping[str, Any],
    coroutine: Coroutine[Any, Any, Any],
) -> asyncio.Task[Any]:
    """Create and retain a background task, logging unexpected failures."""
    task = asyncio.create_task(coroutine)
    tasks: set[asyncio.Task[Any]] = bot_data.setdefault(_VOICE_TASKS_KEY, set())
    tasks.add(task)

    def _task_done(completed: asyncio.Task[Any]) -> None:
        tasks.discard(completed)
        if completed.cancelled():
            return
        error = completed.exception()
        if error is not None:
            LOGGER.error(
                "Voice background task failed",
                exc_info=(type(error), error, error.__traceback__),
            )

    task.add_done_callback(_task_done)
    return task


def voice_worker_id(bot_data: MutableMapping[str, Any]) -> str:
    """Return a stable id for this bot process, unique across instances."""
    existing = str(bot_data.get(_VOICE_WORKER_ID_KEY, "")).strip()
    if existing:
        return existing
    owner = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex}"[:128]
    bot_data[_VOICE_WORKER_ID_KEY] = owner
    return owner


async def resume_pending_voice_jobs(application: Any, *, batch_size: int = 10) -> int:
    """Claim and schedule one due batch.

    This is safe to call at startup and repeatedly while the process is live.
    Overlapping instances cannot schedule the same row because the claim is a
    database transaction using ``FOR UPDATE SKIP LOCKED`` plus a lease.
    """
    bot_data = application.bot_data
    session_factory = bot_data.get("session_factory")
    facade = bot_data.get("facade")
    bot_token = str(bot_data.get("bot_token", ""))
    if session_factory is None or not bot_token or not isinstance(facade, AssistantFacade):
        LOGGER.warning("Voice recovery skipped because runtime dependencies are incomplete")
        return 0

    # A process id identifies the runtime in logs, but every claim cycle needs
    # a fresh fencing token. If an old task outlives its lease, a later claim
    # in the same process must not accidentally make that stale task valid.
    owner = f"{voice_worker_id(bot_data)[:90]}:{uuid.uuid4().hex}"
    states = await claim_recoverable_voice_media_events(
        session_factory,
        lease_owner=owner,
        lease_seconds=VOICE_LEASE_SECONDS,
        limit=batch_size,
    )
    for state in states:
        schedule_voice_task(
            bot_data,
            run_claimed_voice_event(
                bot_data=bot_data,
                event_id=state.id,
                lease_owner=owner,
            ),
        )

    if states:
        LOGGER.info("Scheduled claimed voice recovery jobs count=%s", len(states))
    return len(states)


async def run_claimed_voice_event(
    *,
    bot_data: MutableMapping[str, Any],
    event_id: uuid.UUID,
    lease_owner: str,
) -> None:
    """Run one already-claimed event while renewing and verifying its lease."""
    session_factory = bot_data.get("session_factory")
    facade = bot_data.get("facade")
    bot_token = str(bot_data.get("bot_token", ""))
    media_dir = str(bot_data.get("voice_media_dir", "/tmp/dream_voice"))
    if session_factory is None or not bot_token or not isinstance(facade, AssistantFacade):
        LOGGER.error("Claimed voice job lacks runtime dependencies event_id=%s", event_id)
        return

    stop_heartbeat = asyncio.Event()
    lease_lost = asyncio.Event()
    heartbeat = asyncio.create_task(
        _voice_lease_heartbeat(
            session_factory,
            event_id=event_id,
            lease_owner=lease_owner,
            stop=stop_heartbeat,
            lease_lost=lease_lost,
        )
    )
    try:
        state = await get_voice_media_event(
            session_factory,
            event_id,
            lease_owner=lease_owner,
        )
        if state is None:
            LOGGER.info("Voice event lease was lost before run event_id=%s", event_id)
            return
        if state.status == "reply_pending":
            await deliver_pending_voice_reply(
                event_id=event_id,
                chat_id=state.chat_id,
                telegram_bot_token=bot_token,
                session_factory=session_factory,
                lease_owner=lease_owner,
                lease_lost=lease_lost,
            )
            return

        local_path = state.local_path
        tracked_path = (
            resolve_voice_media_path(local_path, media_dir=media_dir) if local_path else None
        )
        if state.transcript_text is None and (tracked_path is None or not tracked_path.is_file()):
            if local_path:
                LOGGER.warning(
                    "Tracked voice media is missing; downloading again event_id=%s",
                    event_id,
                )
            local_path = ""
            try:
                from telegram import Bot

                _raise_if_voice_lease_lost(lease_lost, event_id=event_id)
                async with Bot(token=bot_token) as bot:
                    local_path = await _await_while_voice_lease_owned(
                        download_voice_file_by_id(
                            bot,
                            file_id=state.telegram_file_id,
                            media_dir=media_dir,
                            event_id=event_id,
                        ),
                        lease_lost=lease_lost,
                        event_id=event_id,
                        operation="download",
                    )
                await store_voice_media_path(
                    session_factory,
                    event_id,
                    local_path,
                    lease_owner=lease_owner,
                )
            except VoiceLeaseLost:
                LOGGER.info("Voice lease lost during recovered download event_id=%s", event_id)
                delete_local_voice_file(local_path, media_dir=media_dir)
                return
            except Exception:
                LOGGER.exception("Recovered voice download failed event_id=%s", event_id)
                delete_local_voice_file(local_path, media_dir=media_dir)
                await release_voice_media_lease(
                    session_factory,
                    event_id,
                    lease_owner=lease_owner,
                    retry_delay_seconds=_DOWNLOAD_RETRY_SECONDS,
                )
                return

        await transcribe_and_reply(
            event_id=event_id,
            local_path=local_path,
            chat_id=state.chat_id,
            telegram_bot_token=bot_token,
            session_factory=session_factory,
            facade=facade,
            media_dir=media_dir,
            lease_owner=lease_owner,
            state_store=bot_data.get("operational_state_store"),
            lease_lost=lease_lost,
        )
    except VoiceLeaseLost:
        LOGGER.info("Voice worker stopped after losing lease event_id=%s", event_id)
    finally:
        stop_heartbeat.set()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat
        await release_voice_media_lease(
            session_factory,
            event_id,
            lease_owner=lease_owner,
        )


async def _voice_lease_heartbeat(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    event_id: uuid.UUID,
    lease_owner: str,
    stop: asyncio.Event,
    lease_lost: asyncio.Event,
) -> None:
    interval = max(1.0, VOICE_LEASE_SECONDS / 3)
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            return
        except TimeoutError:
            try:
                renewed = await renew_voice_media_lease(
                    session_factory,
                    event_id,
                    lease_owner=lease_owner,
                    lease_seconds=VOICE_LEASE_SECONDS,
                )
            except Exception:
                LOGGER.exception("Voice lease heartbeat failed event_id=%s", event_id)
                # Without a successful renewal we can no longer prove ownership.
                # Stop external side effects conservatively and let recovery claim
                # the durable row after the existing lease expires.
                lease_lost.set()
                return
            if not renewed:
                LOGGER.warning("Voice lease heartbeat lost ownership event_id=%s", event_id)
                lease_lost.set()
                return


def _raise_if_voice_lease_lost(
    lease_lost: asyncio.Event | None,
    *,
    event_id: uuid.UUID,
) -> None:
    if lease_lost is not None and lease_lost.is_set():
        raise VoiceLeaseLost(f"Voice lease lost for event {event_id}")


async def _await_while_voice_lease_owned(
    awaitable: Awaitable[_T],
    *,
    lease_lost: asyncio.Event | None,
    event_id: uuid.UUID,
    operation: str,
) -> _T:
    """Cancel one external operation as soon as its durable lease is lost."""
    if lease_lost is None:
        return await awaitable

    if lease_lost.is_set():
        if asyncio.iscoroutine(awaitable):
            awaitable.close()
        raise VoiceLeaseLost(f"Voice lease lost before {operation} for event {event_id}")

    work_task = asyncio.ensure_future(awaitable)
    lease_task = asyncio.create_task(lease_lost.wait())
    try:
        done, _pending = await asyncio.wait(
            {work_task, lease_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if lease_task in done and lease_lost.is_set():
            work_task.cancel()
            await asyncio.gather(work_task, return_exceptions=True)
            raise VoiceLeaseLost(f"Voice lease lost during {operation} for event {event_id}")

        result = await work_task
        _raise_if_voice_lease_lost(lease_lost, event_id=event_id)
        return result
    finally:
        lease_task.cancel()
        if not work_task.done():
            work_task.cancel()
        await asyncio.gather(work_task, lease_task, return_exceptions=True)


async def transcribe_and_reply(
    *,
    event_id: uuid.UUID,
    local_path: str,
    chat_id: int,
    telegram_bot_token: str,
    session_factory: async_sessionmaker[AsyncSession],
    facade: AssistantFacade,
    media_dir: str = "/tmp/dream_voice",
    lease_owner: str | None = None,
    state_store: Any = None,
    lease_lost: asyncio.Event | None = None,
) -> None:
    """Advance a voice job once; leased failures return for supervisor retry."""
    _raise_if_voice_lease_lost(lease_lost, event_id=event_id)
    owner_kwargs = {"lease_owner": lease_owner} if lease_owner is not None else {}
    state = await get_voice_media_event(session_factory, event_id, **owner_kwargs)
    if state is None:
        LOGGER.error("Voice event disappeared or lease expired event_id=%s", event_id)
        return
    if state.status in {"delivered", "done"}:
        return
    if state.status == "reply_pending":
        await deliver_pending_voice_reply(
            event_id=event_id,
            chat_id=chat_id,
            telegram_bot_token=telegram_bot_token,
            session_factory=session_factory,
            lease_owner=lease_owner,
            lease_lost=lease_lost,
        )
        return
    if state.status == "transcription_failed":
        # The final provider attempt and reply staging are two commits. If the
        # process dies between them, recovery must deliver the terminal result
        # without paying for a fourth transcription attempt.
        await stage_and_deliver_voice_reply(
            event_id=event_id,
            chat_id=chat_id,
            telegram_bot_token=telegram_bot_token,
            session_factory=session_factory,
            reply_text=_TRANSCRIPTION_FAILED_MESSAGE,
            local_path=state.local_path or local_path,
            media_dir=media_dir,
            lease_owner=lease_owner,
            lease_lost=lease_lost,
        )
        return

    durable_path = state.local_path or local_path
    safe_path = (
        resolve_voice_media_path(durable_path, media_dir=media_dir) if durable_path else None
    )
    transcript = state.transcript_text
    transcript_was_stored = transcript is not None
    while transcript is None:
        if safe_path is None:
            await stage_and_deliver_voice_reply(
                event_id=event_id,
                chat_id=chat_id,
                telegram_bot_token=telegram_bot_token,
                session_factory=session_factory,
                reply_text=_INTERRUPTED_MESSAGE,
                local_path="",
                media_dir=media_dir,
                lease_owner=lease_owner,
                lease_lost=lease_lost,
            )
            return

        await update_voice_media_event_status(
            session_factory,
            event_id,
            "processing",
            **owner_kwargs,
        )
        try:
            transcript = await _await_while_voice_lease_owned(
                _transcribe_file(str(safe_path)),
                lease_lost=lease_lost,
                event_id=event_id,
                operation="transcription",
            )
            transcript = transcript.strip()
            if not transcript:
                raise RuntimeError("Voice transcription returned empty text")
        except VoiceLeaseLost:
            raise
        except Exception:
            attempt_index = min(
                state.transcription_attempt_count,
                len(_TRANSCRIPTION_RETRY_DELAYS_SECONDS) - 1,
            )
            delay = _TRANSCRIPTION_RETRY_DELAYS_SECONDS[attempt_index]
            attempts = await record_voice_transcription_failure(
                session_factory,
                event_id,
                max_attempts=_MAX_TRANSCRIPTION_ATTEMPTS,
                retry_delay_seconds=delay,
                **owner_kwargs,
            )
            if attempts >= _MAX_TRANSCRIPTION_ATTEMPTS:
                LOGGER.exception(
                    "Transcription permanently failed event_id=%s attempts=%s",
                    event_id,
                    attempts,
                )
                await stage_and_deliver_voice_reply(
                    event_id=event_id,
                    chat_id=chat_id,
                    telegram_bot_token=telegram_bot_token,
                    session_factory=session_factory,
                    reply_text=_TRANSCRIPTION_FAILED_MESSAGE,
                    local_path=str(safe_path),
                    media_dir=media_dir,
                    lease_owner=lease_owner,
                    lease_lost=lease_lost,
                )
                return

            LOGGER.warning(
                "Transcription attempt failed; durable retry scheduled event_id=%s attempt=%s",
                event_id,
                attempts,
            )
            if lease_owner is not None:
                return
            # Compatibility for direct callers outside the leased worker. Live
            # production jobs always return above and are retried by the supervisor.
            await asyncio.sleep(delay)
            state = await get_voice_media_event(session_factory, event_id) or state

    if not transcript_was_stored:
        _raise_if_voice_lease_lost(lease_lost, event_id=event_id)
        LOGGER.info("Transcription succeeded event_id=%s chars=%s", event_id, len(transcript))
        await store_voice_transcript(
            session_factory,
            event_id,
            transcript,
            **owner_kwargs,
        )

    try:
        await update_voice_media_event_status(
            session_factory,
            event_id,
            "processing",
            **owner_kwargs,
        )
        reply_text = await _await_while_voice_lease_owned(
            _build_voice_reply(
                transcript,
                chat_id=chat_id,
                session_factory=session_factory,
                facade=facade,
                state_store=state_store,
                source_message_id=state.telegram_message_id,
            ),
            lease_lost=lease_lost,
            event_id=event_id,
            operation="assistant reply",
        )
    except VoiceLeaseLost:
        raise
    except Exception:
        LOGGER.exception("Voice assistant processing failed for event_id=%s", event_id)
        reply_text = _PROCESSING_FAILED_MESSAGE

    await stage_and_deliver_voice_reply(
        event_id=event_id,
        chat_id=chat_id,
        telegram_bot_token=telegram_bot_token,
        session_factory=session_factory,
        reply_text=reply_text,
        local_path=str(safe_path) if safe_path is not None else "",
        media_dir=media_dir,
        lease_owner=lease_owner,
        lease_lost=lease_lost,
    )


async def _build_voice_reply(
    transcript: str,
    *,
    chat_id: int,
    session_factory: async_sessionmaker[AsyncSession],
    facade: AssistantFacade,
    state_store: Any = None,
    source_message_id: int | None = None,
) -> str:
    source_event_key = _telegram_source_event_key(chat_id, source_message_id)
    direct_note_text = _extract_direct_note_text(transcript)
    if direct_note_text is not None:
        _success, reply = await facade.add_dream_note(direct_note_text, chat_id=chat_id)
        return reply

    if _has_natural_dream_opening(transcript.casefold()):
        create_kwargs: dict[str, Any] = {"chat_id": chat_id}
        if source_event_key is not None:
            create_kwargs["source_event_key"] = source_event_key
        created = await facade.create_dream(transcript, **create_kwargs)
        return _format_create_dream_reply(created)

    chat_kwargs: dict[str, Any] = {
        "session_factory": session_factory,
        "chat_id": chat_id,
    }
    if state_store is not None:
        chat_kwargs["operational_state_store"] = state_store
    if source_event_key is not None:
        chat_kwargs["source_event_key"] = source_event_key
    result = await handle_chat_with_metadata(transcript, facade, **chat_kwargs)
    await _maybe_store_pending_dream(
        result,
        transcript,
        chat_id=chat_id,
        source_message_id=source_message_id,
        source_kind="voice_transcript",
        state_store=state_store,
    )
    return result.text


async def stage_and_deliver_voice_reply(
    *,
    event_id: uuid.UUID,
    chat_id: int,
    telegram_bot_token: str,
    session_factory: async_sessionmaker[AsyncSession],
    reply_text: str,
    local_path: str,
    media_dir: str,
    lease_owner: str | None = None,
    lease_lost: asyncio.Event | None = None,
) -> bool:
    """Persist a reply first, remove raw media, then attempt delivery."""
    _raise_if_voice_lease_lost(lease_lost, event_id=event_id)
    owner_kwargs = {"lease_owner": lease_owner} if lease_owner is not None else {}
    reply_text = reply_text.strip()
    if not reply_text:
        LOGGER.error("Voice reply builder returned blank text event_id=%s", event_id)
        reply_text = _PROCESSING_FAILED_MESSAGE
    await store_voice_reply_pending(
        session_factory,
        event_id,
        reply_text,
        **owner_kwargs,
    )
    _raise_if_voice_lease_lost(lease_lost, event_id=event_id)
    delete_local_voice_file(local_path, media_dir=media_dir)
    return await deliver_pending_voice_reply(
        event_id=event_id,
        chat_id=chat_id,
        telegram_bot_token=telegram_bot_token,
        session_factory=session_factory,
        lease_owner=lease_owner,
        lease_lost=lease_lost,
    )


async def deliver_pending_voice_reply(
    *,
    event_id: uuid.UUID,
    chat_id: int,
    telegram_bot_token: str,
    session_factory: async_sessionmaker[AsyncSession],
    lease_owner: str | None = None,
    lease_lost: asyncio.Event | None = None,
) -> bool:
    """Deliver a staged reply with a durable chunk cursor and retry backoff."""
    _raise_if_voice_lease_lost(lease_lost, event_id=event_id)
    owner_kwargs = {"lease_owner": lease_owner} if lease_owner is not None else {}
    state = await get_voice_media_event(session_factory, event_id, **owner_kwargs)
    if state is None or state.status == "delivered":
        return state is not None
    reply_text = state.reply_text.strip() if state.reply_text is not None else ""
    if not reply_text:
        LOGGER.error("Voice reply is pending without text event_id=%s", event_id)
        try:
            await mark_voice_reply_failed(session_factory, event_id, **owner_kwargs)
        except VoiceLeaseLost:
            LOGGER.info(
                "Voice lease lost before marking malformed reply failed event_id=%s", event_id
            )
        except LookupError:
            LOGGER.info(
                "Voice reply disappeared before malformed reply failure event_id=%s", event_id
            )
        return False
    chunks = _split_telegram_text(reply_text)
    start_index = min(max(state.reply_chunks_delivered, 0), len(chunks))
    try:
        for index in range(start_index, len(chunks)):
            _raise_if_voice_lease_lost(lease_lost, event_id=event_id)
            if lease_owner is not None:
                owned = await get_voice_media_event(
                    session_factory,
                    event_id,
                    lease_owner=lease_owner,
                )
                if owned is None:
                    raise VoiceLeaseLost(f"Voice lease lost before delivery for {event_id}")
            await _await_while_voice_lease_owned(
                _send_telegram_message(telegram_bot_token, chat_id, chunks[index]),
                lease_lost=lease_lost,
                event_id=event_id,
                operation="reply delivery",
            )
            _raise_if_voice_lease_lost(lease_lost, event_id=event_id)
            await store_voice_delivery_progress(
                session_factory,
                event_id,
                index + 1,
                **owner_kwargs,
            )
    except VoiceLeaseLost:
        LOGGER.info("Voice reply delivery stopped after lease loss event_id=%s", event_id)
        return False
    except Exception:
        LOGGER.exception("Voice reply delivery failed event_id=%s", event_id)
        if lease_owner is not None:
            delay_index = min(
                state.delivery_attempt_count,
                len(_DELIVERY_RETRY_DELAYS_SECONDS) - 1,
            )
            await record_voice_delivery_failure(
                session_factory,
                event_id,
                retry_delay_seconds=_DELIVERY_RETRY_DELAYS_SECONDS[delay_index],
                lease_owner=lease_owner,
            )
        return False
    _raise_if_voice_lease_lost(lease_lost, event_id=event_id)
    await mark_voice_reply_delivered(session_factory, event_id, **owner_kwargs)
    return True


def start_voice_maintenance_supervisor(
    application: Any,
    *,
    poll_interval_seconds: float = 5.0,
    cleanup_interval_seconds: float = 300.0,
    batch_size: int = 10,
) -> asyncio.Task[Any]:
    """Start one live retry/retention loop; repeated calls return the same task."""
    bot_data = application.bot_data
    existing = bot_data.get(_VOICE_SUPERVISOR_TASK_KEY)
    if isinstance(existing, asyncio.Task) and not existing.done():
        return existing
    stop = asyncio.Event()
    task = asyncio.create_task(
        voice_maintenance_supervisor(
            application,
            stop=stop,
            poll_interval_seconds=poll_interval_seconds,
            cleanup_interval_seconds=cleanup_interval_seconds,
            batch_size=batch_size,
        )
    )
    bot_data[_VOICE_SUPERVISOR_STOP_KEY] = stop
    bot_data[_VOICE_SUPERVISOR_TASK_KEY] = task
    return task


async def stop_voice_maintenance_supervisor(application: Any) -> None:
    """Stop the supervisor and cancel/await retained per-event tasks."""
    bot_data = application.bot_data
    stop = bot_data.pop(_VOICE_SUPERVISOR_STOP_KEY, None)
    task = bot_data.pop(_VOICE_SUPERVISOR_TASK_KEY, None)
    if isinstance(stop, asyncio.Event):
        stop.set()
    if isinstance(task, asyncio.Task):
        supervisor_waiter = asyncio.gather(task, return_exceptions=True)
        try:
            await asyncio.wait_for(
                asyncio.shield(supervisor_waiter),
                timeout=VOICE_SUPERVISOR_STOP_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            LOGGER.warning("Cancelling voice maintenance supervisor after shutdown timeout")
            task.cancel()
            await _cancel_tasks_bounded(
                {task},
                timeout=VOICE_SUPERVISOR_STOP_TIMEOUT_SECONDS,
                label="voice maintenance supervisor",
            )

    active_tasks: set[asyncio.Task[Any]] = bot_data.pop(_VOICE_TASKS_KEY, set())
    await _cancel_tasks_bounded(
        active_tasks,
        timeout=VOICE_ACTIVE_TASK_STOP_TIMEOUT_SECONDS,
        label="voice event workers",
    )


async def _cancel_tasks_bounded(
    tasks: set[asyncio.Task[Any]],
    *,
    timeout: float,
    label: str,
) -> None:
    live_tasks = {task for task in tasks if not task.done()}
    for task in live_tasks:
        task.cancel()
    if not live_tasks:
        return

    done, pending = await asyncio.wait(live_tasks, timeout=max(timeout, 0.0))
    for completed in done:
        if completed.cancelled():
            continue
        error = completed.exception()
        if error is not None:
            LOGGER.error(
                "%s failed during shutdown",
                label,
                exc_info=(type(error), error, error.__traceback__),
            )
    if pending:
        LOGGER.error(
            "%s did not stop before the bounded shutdown deadline count=%s",
            label,
            len(pending),
        )


async def voice_maintenance_supervisor(
    application: Any,
    *,
    stop: asyncio.Event,
    poll_interval_seconds: float,
    cleanup_interval_seconds: float,
    batch_size: int,
) -> None:
    """Periodically recover jobs and enforce raw/transcript retention."""
    last_cleanup = float("-inf")
    while not stop.is_set():
        try:
            await resume_pending_voice_jobs(application, batch_size=batch_size)
        except Exception:
            LOGGER.exception("Voice live recovery cycle failed")

        now = time.monotonic()
        if now - last_cleanup >= cleanup_interval_seconds:
            try:
                await run_voice_retention_cycle(application)
            except Exception:
                LOGGER.exception("Voice periodic retention cycle failed")
            last_cleanup = now

        try:
            await asyncio.wait_for(stop.wait(), timeout=max(poll_interval_seconds, 0.1))
        except TimeoutError:
            continue


async def run_voice_retention_cycle(application: Any) -> tuple[int, int, int]:
    """Run one operational-data retention cycle.

    The historical three-count return value remains stable for callers.  Bot
    session deletion is independently logged by aggregate count.
    """
    bot_data = application.bot_data
    session_factory = bot_data.get("session_factory")
    if session_factory is None:
        return 0, 0, 0
    settings = get_settings()
    media_dir = str(bot_data.get("voice_media_dir", settings.VOICE_MEDIA_DIR))
    # Purge persisted conversation text first so an unrelated filesystem
    # cleanup failure cannot defer the privacy deadline.
    await purge_expired_bot_sessions(
        session_factory,
        retention_seconds=HISTORY_TTL_SECONDS,
    )
    deleted = await cleanup_voice_media(
        session_factory,
        retention_seconds=settings.VOICE_RETENTION_SECONDS,
        media_dir=media_dir,
    )
    orphans = await cleanup_orphan_voice_files(
        session_factory,
        retention_seconds=settings.VOICE_RETENTION_SECONDS,
        media_dir=media_dir,
    )
    transcripts = await purge_expired_voice_transcripts(
        session_factory,
        retention_seconds=settings.VOICE_TRANSCRIPT_RETENTION_SECONDS,
    )
    return deleted, orphans, transcripts


async def _transcribe_file(local_path: str) -> str:
    """Call Whisper with a cancellable, bounded, single-attempt transport."""
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set — transcription unavailable")
    from openai import AsyncOpenAI

    path = Path(local_path)

    async def _request() -> str:
        async with AsyncOpenAI(
            api_key=api_key,
            timeout=_WHISPER_TIMEOUT_SECONDS,
            max_retries=0,
        ) as client:
            with path.open("rb") as audio_file:
                response = await client.audio.transcriptions.create(
                    model=_WHISPER_MODEL,
                    file=audio_file,
                )
        transcript = response.text.strip()
        if not transcript:
            raise RuntimeError("Whisper returned empty transcript")
        return transcript

    return await asyncio.wait_for(_request(), timeout=_WHISPER_TIMEOUT_SECONDS)


async def _send_telegram_message(bot_token: str, chat_id: int, text: str) -> None:
    """Send via Bot API and raise so the durable outbox remains retryable."""
    from telegram import Bot

    async with Bot(token=bot_token) as bot:
        await bot.send_message(chat_id=chat_id, text=text)

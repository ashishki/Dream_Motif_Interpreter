"""Voice-file download utility for the Telegram bot.

Downloads a Telegram voice message to the configured local media directory.
Raw audio is temporary operational data — not part of the dream archive.
"""

from __future__ import annotations

import contextlib
import logging
import os
import uuid
from pathlib import Path
from typing import Any

from telegram import Update
from telegram.ext import ContextTypes

LOGGER = logging.getLogger(__name__)


async def download_voice_file(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    media_dir: str,
    event_id: uuid.UUID | None = None,
) -> str:
    """Download the voice attachment from a Telegram update to a local .ogg file.

    Returns the absolute path of the downloaded file.
    Raises RuntimeError on download failure.
    """
    message = update.effective_message
    if message is None or message.voice is None:
        raise ValueError("No voice attachment in update")

    return await download_voice_file_by_id(
        context.bot,
        file_id=message.voice.file_id,
        media_dir=media_dir,
        event_id=event_id,
    )


async def download_voice_file_by_id(
    bot: Any,
    *,
    file_id: str,
    media_dir: str,
    event_id: uuid.UUID | None = None,
) -> str:
    """Atomically download a Telegram file to a deterministic event path.

    A ``.part`` file is never persisted in the database and is removed on a
    handled failure. The periodic orphan sweep covers process death between the
    download and ``os.replace``.
    """
    dest_dir = Path(media_dir).resolve()
    dest_dir.mkdir(parents=True, exist_ok=True)
    stable_name = str(event_id) if event_id is not None else uuid.uuid4().hex
    dest_path = dest_dir / f"{stable_name}.ogg"
    temporary_path = dest_dir / f"{stable_name}.ogg.part"

    try:
        telegram_file = await bot.get_file(file_id)
        await telegram_file.download_to_drive(custom_path=str(temporary_path))
        os.replace(temporary_path, dest_path)
    except Exception as exc:
        with contextlib.suppress(OSError):
            temporary_path.unlink(missing_ok=True)
        LOGGER.exception("Failed to download Telegram voice file_id=%s", file_id)
        raise RuntimeError(f"Voice download failed for file_id={file_id}") from exc

    LOGGER.info("Downloaded voice file to path=%s", dest_path.name)
    return str(dest_path)

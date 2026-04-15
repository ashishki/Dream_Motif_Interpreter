"""Voice-file download utility for the Telegram bot.

Downloads a Telegram voice message to the configured local media directory.
Raw audio is temporary operational data — not part of the dream archive.
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes

LOGGER = logging.getLogger(__name__)


async def download_voice_file(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    media_dir: str,
) -> str:
    """Download the voice attachment from a Telegram update to a local .ogg file.

    Returns the absolute path of the downloaded file.
    Raises RuntimeError on download failure.
    """
    message = update.effective_message
    if message is None or message.voice is None:
        raise ValueError("No voice attachment in update")

    file_id = message.voice.file_id
    dest_dir = Path(media_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    dest_path = dest_dir / f"{file_id}_{uuid.uuid4().hex[:8]}.ogg"

    try:
        telegram_file = await context.bot.get_file(file_id)
        await telegram_file.download_to_drive(custom_path=str(dest_path))
    except Exception as exc:
        LOGGER.exception("Failed to download Telegram voice file_id=%s", file_id)
        raise RuntimeError(f"Voice download failed for file_id={file_id}") from exc

    LOGGER.info("Downloaded voice file to path=%s", dest_path.name)
    return str(dest_path)

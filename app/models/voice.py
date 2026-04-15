from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.dream import Base

UUID_SERVER_DEFAULT = text("gen_random_uuid()")
TIMESTAMP_SERVER_DEFAULT = text("CURRENT_TIMESTAMP")


class VoiceMediaEvent(Base):
    """Persisted record of a Telegram voice-message ingress event.

    Created before transcription starts so media metadata is durable
    even if the transcription step fails. The record tracks the lifecycle
    of a single voice note from receipt through transcript delivery.

    voice_media_events is an operational table — it is not part of the
    dream archive. Raw media is deleted on a short retention schedule
    (P7-T03); this table tracks the metadata.
    """

    __tablename__ = "voice_media_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=UUID_SERVER_DEFAULT,
    )
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    telegram_message_id: Mapped[int] = mapped_column(Integer, nullable=False)
    telegram_file_id: Mapped[str] = mapped_column(String(512), nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    local_path: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default=text("'received'"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=TIMESTAMP_SERVER_DEFAULT
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=TIMESTAMP_SERVER_DEFAULT
    )

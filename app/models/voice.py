from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, Text, UniqueConstraint, text
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
    __table_args__ = (
        UniqueConstraint(
            "chat_id",
            "telegram_message_id",
            name="uq_voice_media_events_chat_message",
        ),
        Index(
            "ix_voice_media_events_recovery",
            "status",
            "next_attempt_at",
            "lease_expires_at",
        ),
    )

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
    transcript_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    reply_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcription_attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    reply_chunks_delivered: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    delivery_attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
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

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, text as sa_text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.dream import Base

UUID_SERVER_DEFAULT = sa_text("gen_random_uuid()")
TIMESTAMP_SERVER_DEFAULT = sa_text("now()")


class DreamNote(Base):
    __tablename__ = "dream_notes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        nullable=False,
        server_default=UUID_SERVER_DEFAULT,
    )
    dream_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dream_entries.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    text: Mapped[str] = mapped_column(Text(), nullable=False)
    source: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        server_default=sa_text("'telegram'"),
        default="telegram",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=TIMESTAMP_SERVER_DEFAULT,
    )

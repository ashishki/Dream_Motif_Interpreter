from __future__ import annotations

from typing import Any, Dict

import sqlalchemy as sa
from sqlalchemy import SmallInteger, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.dream import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AssistantFeedback(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "assistant_feedback"

    chat_id: Mapped[str] = mapped_column(Text(), nullable=False)
    context: Mapped[Dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sa.text("'{}'::jsonb"),
    )
    score: Mapped[int] = mapped_column(SmallInteger(), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text(), nullable=True)

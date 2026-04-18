from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.dream import Base

TIMESTAMP_SERVER_DEFAULT = text("CURRENT_TIMESTAMP")


class BotSession(Base):
    """Persistent conversational session state for the Telegram bot.

    One row per allowed chat. Stores the recent conversation history as JSON so
    the assistant can maintain context across process restarts.
    Session history is operational state — it is not part of the dream archive.
    """

    __tablename__ = "bot_sessions"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    history_json: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'[]'"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=TIMESTAMP_SERVER_DEFAULT
    )

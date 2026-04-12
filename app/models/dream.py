from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import List, Optional

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import UserDefinedType

UUID_SERVER_DEFAULT = text("gen_random_uuid()")
TIMESTAMP_SERVER_DEFAULT = text("CURRENT_TIMESTAMP")


class Base(DeclarativeBase):
    pass


class Vector1536(UserDefinedType):
    cache_ok = True

    def get_col_spec(self, **kw: object) -> str:
        return "vector(1536)"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=TIMESTAMP_SERVER_DEFAULT
    )


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        nullable=False,
        server_default=UUID_SERVER_DEFAULT,
    )


class DreamEntry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "dream_entries"

    source_doc_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    date: Mapped[Optional[date]] = mapped_column(Date(), nullable=True, index=True)
    title: Mapped[str] = mapped_column(Text(), nullable=False)
    raw_text: Mapped[str] = mapped_column(Text(), nullable=False)
    word_count: Mapped[int] = mapped_column(Integer(), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    segmentation_confidence: Mapped[Optional[float]] = mapped_column(Float(), nullable=True)

    chunks: Mapped[List["DreamChunk"]] = relationship(
        back_populates="dream", cascade="all, delete-orphan"
    )
    themes: Mapped[List["DreamTheme"]] = relationship(back_populates="dream")


class DreamChunk(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "dream_chunks"
    __table_args__ = (
        UniqueConstraint("dream_id", "chunk_index", name="uq_dream_chunks_dream_id_chunk_index"),
    )

    dream_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dream_entries.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer(), nullable=False)
    chunk_text: Mapped[str] = mapped_column(Text(), nullable=False)
    embedding: Mapped[Optional[str]] = mapped_column(Vector1536(), nullable=True)

    dream: Mapped["DreamEntry"] = relationship(back_populates="chunks")


from app.models.theme import DreamTheme  # noqa: E402

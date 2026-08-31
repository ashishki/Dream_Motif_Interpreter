from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.dream import Base


class DreamProcessingJob(Base):
    """Durable outbox row for post-capture dream enrichment and delivery."""

    __tablename__ = "dream_processing_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'retryable', 'succeeded', 'failed')",
            name="ck_dream_processing_jobs_status",
        ),
        CheckConstraint(
            "stage IN ('index', 'analysis', 'motif', 'gdocs')",
            name="ck_dream_processing_jobs_stage",
        ),
        UniqueConstraint(
            "dream_id",
            "stage",
            name="uq_dream_processing_jobs_dream_stage",
        ),
        Index(
            "ix_dream_processing_jobs_claim",
            "status",
            "available_at",
            "locked_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        nullable=False,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    dream_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dream_entries.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default=text("'pending'")
    )
    stage: Mapped[str] = mapped_column(
        String(16), nullable=False, default="index", server_default=text("'index'")
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer(), nullable=False, default=0, server_default=text("0")
    )
    last_error: Mapped[str | None] = mapped_column(Text(), nullable=True)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lock_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class NoteProcessingJob(Base):
    """Durable outbox row for note indexing and Google Docs delivery."""

    __tablename__ = "note_processing_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'retryable', 'succeeded', 'failed')",
            name="ck_note_processing_jobs_status",
        ),
        CheckConstraint(
            "stage IN ('index', 'gdocs')",
            name="ck_note_processing_jobs_stage",
        ),
        CheckConstraint(
            "(stage = 'gdocs' AND target_doc_id IS NOT NULL) "
            "OR (stage = 'index' AND target_doc_id IS NULL)",
            name="ck_note_processing_jobs_target",
        ),
        UniqueConstraint(
            "note_id",
            "stage",
            name="uq_note_processing_jobs_note_stage",
        ),
        Index(
            "ix_note_processing_jobs_claim",
            "status",
            "available_at",
            "locked_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        nullable=False,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    note_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dream_notes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stage: Mapped[str] = mapped_column(
        String(16), nullable=False, default="index", server_default=text("'index'")
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default=text("'pending'")
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer(), nullable=False, default=0, server_default=text("0")
    )
    last_error: Mapped[str | None] = mapped_column(Text(), nullable=True)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lock_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    target_doc_id: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

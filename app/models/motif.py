from __future__ import annotations

import uuid
from typing import Any, Dict, List, Literal

import sqlalchemy as sa
from sqlalchemy import CheckConstraint, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.dream import Base, TimestampMixin, UUIDPrimaryKeyMixin

MotifConfidence = Literal["high", "moderate", "low"]
MotifStatus = Literal["draft", "confirmed", "rejected"]


class MotifInduction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "motif_inductions"
    __table_args__ = (
        CheckConstraint(
            "confidence IN ('high', 'moderate', 'low')",
            name="ck_motif_inductions_confidence",
        ),
        CheckConstraint(
            "status IN ('draft', 'confirmed', 'rejected')",
            name="ck_motif_inductions_status",
        ),
    )

    dream_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dream_entries.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    label: Mapped[str] = mapped_column(Text(), nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text(), nullable=True)
    confidence: Mapped[str | None] = mapped_column(String(16), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default=sa.text("'draft'"),
    )
    fragments: Mapped[List[Dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sa.text("'[]'::jsonb"),
    )
    model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)

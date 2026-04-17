from __future__ import annotations

import uuid
from typing import Any, Dict, List

import sqlalchemy as sa
from sqlalchemy import ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.dream import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ResearchResult(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "research_results"

    motif_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("motif_inductions.id", ondelete="CASCADE"),
        nullable=False,
    )
    dream_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dream_entries.id", ondelete="CASCADE"),
        nullable=False,
    )
    query_label: Mapped[str] = mapped_column(Text(), nullable=False)
    parallels: Mapped[List[Dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sa.text("'[]'::jsonb"),
    )
    sources: Mapped[List[Dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sa.text("'[]'::jsonb"),
    )
    triggered_by: Mapped[str] = mapped_column(Text(), nullable=False)

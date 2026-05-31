from __future__ import annotations

from typing import Any, Dict

import sqlalchemy as sa
from sqlalchemy import CheckConstraint, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.dream import Base, TimestampMixin, UUIDPrimaryKeyMixin


class DreamGraphPrivacyControl(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "dream_graph_privacy_controls"
    __table_args__ = (
        CheckConstraint(
            "subject_type IN ('dream', 'graph_node', 'graph_edge')",
            name="ck_dream_graph_privacy_controls_subject_type",
        ),
        CheckConstraint(
            "action IN ('delete', 'hide')",
            name="ck_dream_graph_privacy_controls_action",
        ),
    )

    subject_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    subject_id: Mapped[str] = mapped_column(Text(), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    control_payload: Mapped[Dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sa.text("'{}'::jsonb"),
    )
    receipt_payload: Mapped[Dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sa.text("'{}'::jsonb"),
    )
    changed_by: Mapped[str] = mapped_column(String(255), nullable=False)

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Literal

from sqlalchemy import CheckConstraint, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.dream import Base, TimestampMixin, UUIDPrimaryKeyMixin

ThemeCategoryStatus = Literal["suggested", "active", "deprecated"]


class ThemeCategory(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "theme_categories"
    __table_args__ = (
        CheckConstraint(
            "status IN ('suggested', 'active', 'deprecated')",
            name="ck_theme_categories_status",
        ),
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    status: Mapped[ThemeCategoryStatus] = mapped_column(String(32), nullable=False)

    dream_themes: Mapped[List["DreamTheme"]] = relationship(back_populates="category")


class DreamTheme(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "dream_themes"

    dream_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dream_entries.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("theme_categories.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    salience: Mapped[float] = mapped_column(Float(), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    match_type: Mapped[str] = mapped_column(String(64), nullable=False)
    fragments: Mapped[List[Dict[str, Any]]] = mapped_column(JSONB, nullable=False)

    dream: Mapped["DreamEntry"] = relationship(back_populates="themes")
    category: Mapped["ThemeCategory"] = relationship(back_populates="dream_themes")


from app.models.dream import DreamEntry  # noqa: E402

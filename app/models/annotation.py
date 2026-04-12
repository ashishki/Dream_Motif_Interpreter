from __future__ import annotations

import uuid
from typing import Any, Dict

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.dream import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AnnotationVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "annotation_versions"

    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=False)
    snapshot: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)
    changed_by: Mapped[str] = mapped_column(String(255), nullable=False)

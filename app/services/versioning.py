from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.annotation import AnnotationVersion
from app.models.dream import DreamEntry
from app.models.theme import DreamTheme, ThemeCategory
from app.shared.tracing import get_tracer


def build_dream_theme_transition_version(
    *,
    theme: DreamTheme,
    to_status: str,
    changed_by: str,
) -> AnnotationVersion:
    current_state = _dream_theme_state(theme)
    snapshot = {
        **current_state,
        "status_before": theme.status,
        "status_after": to_status,
        "salience_before": theme.salience,
        "salience_after": theme.salience,
        "match_type_before": theme.match_type,
        "match_type_after": theme.match_type,
        "fragments_before": _coerce_fragments(theme.fragments),
        "fragments_after": _coerce_fragments(theme.fragments),
        "deprecated_before": theme.deprecated,
        "deprecated_after": theme.deprecated,
        "changed_by": changed_by,
    }
    return _annotation_version(
        entity_type="dream_theme",
        entity_id=theme.id,
        snapshot=snapshot,
        changed_by=changed_by,
    )


def build_dream_theme_creation_version(
    *,
    theme_id: uuid.UUID,
    dream_id: uuid.UUID,
    category_id: uuid.UUID,
    salience: float,
    status: str,
    match_type: str,
    fragments: object,
    deprecated: bool,
    changed_by: str,
) -> AnnotationVersion:
    snapshot = {
        "entity_type": "dream_theme",
        "entity_id": str(theme_id),
        "dream_id": str(dream_id),
        "category_id": str(category_id),
        "status": status,
        "salience": salience,
        "match_type": match_type,
        "fragments": _coerce_fragments(fragments),
        "deprecated": deprecated,
        "status_before": None,
        "status_after": status,
        "salience_before": None,
        "salience_after": salience,
        "match_type_before": None,
        "match_type_after": match_type,
        "fragments_before": [],
        "fragments_after": _coerce_fragments(fragments),
        "deprecated_before": None,
        "deprecated_after": deprecated,
        "changed_by": changed_by,
    }
    return _annotation_version(
        entity_type="dream_theme",
        entity_id=theme_id,
        snapshot=snapshot,
        changed_by=changed_by,
    )


def build_dream_theme_update_version(
    *,
    theme: DreamTheme,
    next_salience: float,
    next_match_type: str,
    next_fragments: object,
    changed_by: str,
) -> AnnotationVersion:
    current_state = _dream_theme_state(theme)
    snapshot = {
        **current_state,
        "status_before": theme.status,
        "status_after": theme.status,
        "salience_before": theme.salience,
        "salience_after": next_salience,
        "match_type_before": theme.match_type,
        "match_type_after": next_match_type,
        "fragments_before": _coerce_fragments(theme.fragments),
        "fragments_after": _coerce_fragments(next_fragments),
        "deprecated_before": theme.deprecated,
        "deprecated_after": theme.deprecated,
        "changed_by": changed_by,
    }
    return _annotation_version(
        entity_type="dream_theme",
        entity_id=theme.id,
        snapshot=snapshot,
        changed_by=changed_by,
    )


def build_dream_theme_rollback_version(
    *,
    theme: DreamTheme,
    restored_state: dict[str, Any],
    changed_by: str,
) -> AnnotationVersion:
    snapshot = {
        **restored_state,
        "status_before": theme.status,
        "status_after": restored_state["status"],
        "salience_before": theme.salience,
        "salience_after": restored_state["salience"],
        "match_type_before": theme.match_type,
        "match_type_after": restored_state["match_type"],
        "fragments_before": _coerce_fragments(theme.fragments),
        "fragments_after": restored_state["fragments"],
        "deprecated_before": theme.deprecated,
        "deprecated_after": restored_state["deprecated"],
        "changed_by": changed_by,
    }
    return _annotation_version(
        entity_type="dream_theme",
        entity_id=theme.id,
        snapshot=snapshot,
        changed_by=changed_by,
    )


def build_theme_category_creation_version(
    *,
    category_id: uuid.UUID,
    name: str,
    description: str | None,
    status: str,
    changed_by: str,
) -> AnnotationVersion:
    snapshot = {
        "entity_type": "theme_category",
        "entity_id": str(category_id),
        "name": name,
        "description": description,
        "status": status,
        "status_before": None,
        "status_after": status,
        "changed_by": changed_by,
    }
    return _annotation_version(
        entity_type="theme_category",
        entity_id=category_id,
        snapshot=snapshot,
        changed_by=changed_by,
    )


def build_theme_category_transition_version(
    *,
    category: ThemeCategory,
    to_status: str,
    changed_by: str,
) -> AnnotationVersion:
    snapshot = {
        **_theme_category_state(category),
        "status_before": category.status,
        "status_after": to_status,
        "changed_by": changed_by,
    }
    return _annotation_version(
        entity_type="theme_category",
        entity_id=category.id,
        snapshot=snapshot,
        changed_by=changed_by,
    )


class VersioningService:
    @staticmethod
    async def list_theme_history(
        session: AsyncSession,
        *,
        dream_id: uuid.UUID,
    ) -> tuple[DreamEntry, list[AnnotationVersion]]:
        tracer = get_tracer(__name__)

        with tracer.start_as_current_span("db.query.versioning.load_dream"):
            dream = await session.get(DreamEntry, dream_id)
        if dream is None:
            raise HTTPException(status_code=404, detail="Dream not found")

        with tracer.start_as_current_span("db.query.versioning.load_theme_history"):
            result = await session.execute(
                select(AnnotationVersion)
                .join(
                    DreamTheme,
                    DreamTheme.id == AnnotationVersion.entity_id,
                )
                .where(
                    AnnotationVersion.entity_type == "dream_theme",
                    DreamTheme.dream_id == dream_id,
                )
                .order_by(AnnotationVersion.created_at.desc(), AnnotationVersion.id.desc())
            )

        return dream, list(result.scalars().all())

    @staticmethod
    async def rollback_theme(
        session: AsyncSession,
        *,
        dream_id: uuid.UUID,
        theme_id: uuid.UUID,
        version_id: uuid.UUID,
        changed_by: str,
    ) -> DreamTheme:
        tracer = get_tracer(__name__)

        with tracer.start_as_current_span("db.query.versioning.load_theme"):
            result = await session.execute(
                select(DreamTheme).where(
                    DreamTheme.id == theme_id,
                    DreamTheme.dream_id == dream_id,
                )
            )
        theme = result.scalar_one_or_none()
        if theme is None:
            raise HTTPException(status_code=404, detail="Theme not found")

        with tracer.start_as_current_span("db.query.versioning.load_version"):
            version = await session.get(AnnotationVersion, version_id)
        if version is None or version.entity_type != "dream_theme" or version.entity_id != theme.id:
            raise HTTPException(status_code=404, detail="Annotation version not found")

        restored_state = _dream_theme_state_from_snapshot(version.snapshot)
        session.add(
            build_dream_theme_rollback_version(
                theme=theme,
                restored_state=restored_state,
                changed_by=changed_by,
            )
        )
        with tracer.start_as_current_span("db.query.versioning.flush_rollback_annotation"):
            await session.flush()

        theme.category_id = uuid.UUID(restored_state["category_id"])
        theme.status = restored_state["status"]
        theme.salience = restored_state["salience"]
        theme.match_type = restored_state["match_type"]
        theme.fragments = restored_state["fragments"]
        theme.deprecated = restored_state["deprecated"]

        with tracer.start_as_current_span("db.query.versioning.commit_rollback"):
            await session.commit()
        with tracer.start_as_current_span("db.query.versioning.refresh_theme"):
            await session.refresh(theme)
        return theme


def _annotation_version(
    *,
    entity_type: str,
    entity_id: uuid.UUID,
    snapshot: dict[str, Any],
    changed_by: str,
) -> AnnotationVersion:
    return AnnotationVersion(
        entity_type=entity_type,
        entity_id=entity_id,
        snapshot=snapshot,
        changed_by=changed_by,
    )


def _dream_theme_state(theme: DreamTheme) -> dict[str, Any]:
    return {
        "entity_type": "dream_theme",
        "entity_id": str(theme.id),
        "dream_id": str(theme.dream_id),
        "category_id": str(theme.category_id),
        "status": theme.status,
        "salience": theme.salience,
        "match_type": theme.match_type,
        "fragments": _coerce_fragments(theme.fragments),
        "deprecated": theme.deprecated,
    }


def _theme_category_state(category: ThemeCategory) -> dict[str, Any]:
    return {
        "entity_type": "theme_category",
        "entity_id": str(category.id),
        "name": category.name,
        "description": category.description,
        "status": category.status,
    }


def _dream_theme_state_from_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    category_id = _require_snapshot_value(snapshot, "category_id")
    status = _first_snapshot_value(snapshot, "status", "status_before", "status_after")
    salience = _first_snapshot_value(snapshot, "salience", "salience_before", "salience_after")
    match_type = _first_snapshot_value(
        snapshot,
        "match_type",
        "match_type_before",
        "match_type_after",
    )
    fragments = _first_snapshot_value(snapshot, "fragments", "fragments_before", "fragments_after")
    deprecated = _first_snapshot_value(
        snapshot,
        "deprecated",
        "deprecated_before",
        "deprecated_after",
    )

    if status is None or salience is None or match_type is None or deprecated is None:
        raise HTTPException(status_code=409, detail="Annotation version cannot be rolled back")

    return {
        "entity_type": "dream_theme",
        "entity_id": str(_require_snapshot_value(snapshot, "entity_id")),
        "dream_id": str(_require_snapshot_value(snapshot, "dream_id")),
        "category_id": str(category_id),
        "status": str(status),
        "salience": float(salience),
        "match_type": str(match_type),
        "fragments": _coerce_fragments(fragments),
        "deprecated": bool(deprecated),
    }


def _first_snapshot_value(snapshot: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in snapshot and snapshot[key] is not None:
            return snapshot[key]
    return None


def _require_snapshot_value(snapshot: dict[str, Any], key: str) -> Any:
    if key not in snapshot or snapshot[key] is None:
        raise HTTPException(status_code=409, detail="Annotation version cannot be rolled back")
    return snapshot[key]


def _coerce_fragments(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [fragment for fragment in value if isinstance(fragment, dict)]

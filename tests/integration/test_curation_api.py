from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from datetime import date
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.models.annotation import AnnotationVersion
from app.models.dream import DreamEntry
from app.models.theme import DreamTheme, ThemeCategory

PROJECT_ROOT = Path(__file__).resolve().parents[2]
INTERPRETATION_NOTE = (
    "These theme assignments are computational interpretations, not authoritative conclusions."
)


def _alembic_config() -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    return config


async def _reset_public_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.exec_driver_sql("DROP SCHEMA IF EXISTS public CASCADE")
        await connection.exec_driver_sql("CREATE SCHEMA public")
        await connection.exec_driver_sql("GRANT ALL ON SCHEMA public TO public")


def _load_app():
    sys.modules.pop("app.api.search", None)
    sys.modules.pop("app.api.themes", None)
    sys.modules.pop("app.api.dreams", None)
    sys.modules.pop("app.main", None)

    from app.main import app

    return app


class FakeRedis:
    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        del ex
        self._values[key] = value
        return True

    async def get(self, key: str) -> str | None:
        return self._values.get(key)

    async def delete(self, key: str) -> int:
        existed = key in self._values
        self._values.pop(key, None)
        return int(existed)


@pytest_asyncio.fixture
async def migrated_session_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> async_sessionmaker[AsyncSession]:
    database_url = os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://postgres@localhost:5433/dream_motif_test",
    )
    monkeypatch.setenv("DATABASE_URL", database_url)

    reset_engine = create_async_engine(
        database_url,
        poolclass=NullPool,
        connect_args={"statement_cache_size": 0},
    )
    await _reset_public_schema(reset_engine)
    await reset_engine.dispose()
    await asyncio.to_thread(command.upgrade, _alembic_config(), "head")

    engine = create_async_engine(
        database_url,
        poolclass=NullPool,
        connect_args={"statement_cache_size": 0},
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield session_factory
    finally:
        await engine.dispose()


async def _create_dream(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    title: str,
    raw_text: str,
    dream_date: date,
) -> DreamEntry:
    async with session_factory() as session:
        dream = DreamEntry(
            source_doc_id="doc-curation-api",
            date=dream_date,
            title=title,
            raw_text=raw_text,
            word_count=len(raw_text.split()),
            content_hash=f"curation-api-{uuid.uuid4()}",
            segmentation_confidence="high",
        )
        session.add(dream)
        await session.commit()
        await session.refresh(dream)
        return dream


async def _create_category(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    status: str = "active",
    name: str | None = None,
) -> ThemeCategory:
    async with session_factory() as session:
        category = ThemeCategory(
            name=name or f"curation-category-{uuid.uuid4()}",
            description="Theme for curation API tests",
            status=status,
        )
        session.add(category)
        await session.commit()
        await session.refresh(category)
        return category


async def _attach_theme(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    dream_id: uuid.UUID,
    category_id: uuid.UUID,
    status: str = "draft",
    salience: float = 0.75,
    fragment_text: str = "river crossing",
) -> DreamTheme:
    async with session_factory() as session:
        theme = DreamTheme(
            dream_id=dream_id,
            category_id=category_id,
            salience=salience,
            status=status,
            match_type="symbolic",
            fragments=[{"text": fragment_text, "justification": "theme cue"}],
            deprecated=False,
        )
        session.add(theme)
        await session.commit()
        await session.refresh(theme)
        return theme


def _auth_headers() -> dict[str, str]:
    return {"X-API-Key": os.environ["SECRET_KEY"]}


async def _theme_statuses(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    dream_ids: list[uuid.UUID],
) -> dict[tuple[uuid.UUID, uuid.UUID], str]:
    async with session_factory() as session:
        result = await session.execute(
            select(DreamTheme)
            .where(DreamTheme.dream_id.in_(dream_ids))
            .order_by(DreamTheme.created_at.asc())
        )
    return {(theme.dream_id, theme.id): theme.status for theme in result.scalars().all()}


@pytest.mark.anyio
async def test_confirm_theme_transitions_status(
    migrated_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    dream = await _create_dream(
        migrated_session_factory,
        title="Confirmable dream",
        raw_text="A river crossing opens into a bright field.",
        dream_date=date(2026, 4, 13),
    )
    category = await _create_category(migrated_session_factory)
    theme = await _attach_theme(
        migrated_session_factory,
        dream_id=dream.id,
        category_id=category.id,
    )

    async with AsyncClient(
        transport=ASGITransport(app=_load_app()),
        base_url="http://testserver",
    ) as client:
        response = await client.patch(
            f"/dreams/{dream.id}/themes/{theme.id}/confirm",
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    assert response.json() == {
        "dream_id": str(dream.id),
        "theme_id": str(theme.id),
        "category_id": str(category.id),
        "status": "confirmed",
        "interpretation_note": INTERPRETATION_NOTE,
    }

    async with migrated_session_factory() as session:
        refreshed = await session.get(DreamTheme, theme.id)

    assert refreshed is not None
    assert refreshed.status == "confirmed"


@pytest.mark.anyio
async def test_reject_theme_excluded_from_listing(
    migrated_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    dream = await _create_dream(
        migrated_session_factory,
        title="Rejectable dream",
        raw_text="I walked beneath a bridge and heard distant birds.",
        dream_date=date(2026, 4, 14),
    )
    rejected_category = await _create_category(
        migrated_session_factory, name=f"rejected-{uuid.uuid4()}"
    )
    visible_category = await _create_category(
        migrated_session_factory, name=f"visible-{uuid.uuid4()}"
    )
    rejected_theme = await _attach_theme(
        migrated_session_factory,
        dream_id=dream.id,
        category_id=rejected_category.id,
        salience=0.81,
    )
    await _attach_theme(
        migrated_session_factory,
        dream_id=dream.id,
        category_id=visible_category.id,
        status="confirmed",
        salience=0.52,
        fragment_text="distant birds",
    )

    async with AsyncClient(
        transport=ASGITransport(app=_load_app()),
        base_url="http://testserver",
    ) as client:
        reject_response = await client.patch(
            f"/dreams/{dream.id}/themes/{rejected_theme.id}/reject",
            headers=_auth_headers(),
        )
        list_response = await client.get(
            f"/dreams/{dream.id}/themes",
            headers=_auth_headers(),
        )

    assert reject_response.status_code == 200
    assert reject_response.json()["status"] == "rejected"
    assert list_response.status_code == 200
    assert list_response.json() == {
        "dream_id": str(dream.id),
        "themes": [
            {
                "category_id": str(visible_category.id),
                "salience": 0.52,
                "match_type": "symbolic",
                "status": "confirmed",
                "fragments": [{"text": "distant birds", "justification": "theme cue"}],
                "interpretation_note": INTERPRETATION_NOTE,
            }
        ],
    }


@pytest.mark.anyio
async def test_bulk_confirm_requires_approval_step(
    migrated_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_dream = await _create_dream(
        migrated_session_factory,
        title="Bulk confirm one",
        raw_text="A staircase turns into water.",
        dream_date=date(2026, 4, 15),
    )
    second_dream = await _create_dream(
        migrated_session_factory,
        title="Bulk confirm two",
        raw_text="A lantern glows in the cellar.",
        dream_date=date(2026, 4, 16),
    )
    category = await _create_category(migrated_session_factory)
    first_theme = await _attach_theme(
        migrated_session_factory,
        dream_id=first_dream.id,
        category_id=category.id,
        fragment_text="staircase turns into water",
    )
    second_theme = await _attach_theme(
        migrated_session_factory,
        dream_id=second_dream.id,
        category_id=category.id,
        fragment_text="lantern glows in the cellar",
    )

    app = _load_app()
    import app.api.themes as themes_api

    fake_redis = FakeRedis()
    monkeypatch.setattr(themes_api, "_get_redis_client", lambda: fake_redis)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        start_response = await client.post(
            "/curate/bulk-confirm",
            headers=_auth_headers(),
            json={"dream_ids": [str(first_dream.id), str(second_dream.id)]},
        )

        status_before_approval = await _theme_statuses(
            migrated_session_factory,
            dream_ids=[first_dream.id, second_dream.id],
        )

        token = start_response.json()["token"]
        approve_response = await client.post(
            f"/curate/bulk-confirm/{token}/approve",
            headers=_auth_headers(),
        )

    assert start_response.status_code == 200
    assert start_response.json()["requires_approval"] is True
    assert uuid.UUID(start_response.json()["token"])
    assert status_before_approval == {
        (first_dream.id, first_theme.id): "draft",
        (second_dream.id, second_theme.id): "draft",
    }

    assert approve_response.status_code == 200
    assert approve_response.json() == {
        "requires_approval": False,
        "token": token,
        "confirmed_count": 2,
    }

    status_after_approval = await _theme_statuses(
        migrated_session_factory,
        dream_ids=[first_dream.id, second_dream.id],
    )
    assert status_after_approval == {
        (first_dream.id, first_theme.id): "confirmed",
        (second_dream.id, second_theme.id): "confirmed",
    }


@pytest.mark.anyio
async def test_bulk_confirm_approve_returns_410_for_non_list_dream_ids(
    migrated_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del migrated_session_factory
    app = _load_app()
    import app.api.themes as themes_api

    fake_redis = FakeRedis()
    fake_redis._values["bulk_confirm:invalid-dream-ids"] = json.dumps({"dream_ids": "not-a-list"})
    monkeypatch.setattr(themes_api, "_get_redis_client", lambda: fake_redis)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/curate/bulk-confirm/invalid-dream-ids/approve",
            headers=_auth_headers(),
        )

    assert response.status_code == 410
    assert response.json() == {"detail": "Bulk confirmation token has expired"}


@pytest.mark.anyio
async def test_approve_category_requires_auth(
    migrated_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    category = await _create_category(
        migrated_session_factory,
        status="suggested",
        name=f"suggested-{uuid.uuid4()}",
    )

    async with AsyncClient(
        transport=ASGITransport(app=_load_app()),
        base_url="http://testserver",
    ) as client:
        unauthenticated_response = await client.patch(f"/themes/categories/{category.id}/approve")
        authenticated_response = await client.patch(
            f"/themes/categories/{category.id}/approve",
            headers=_auth_headers(),
        )

    assert unauthenticated_response.status_code == 403
    assert authenticated_response.status_code == 200
    assert authenticated_response.json()["status"] == "active"

    async with migrated_session_factory() as session:
        refreshed = await session.get(ThemeCategory, category.id)

    assert refreshed is not None
    assert refreshed.status == "active"


@pytest.mark.anyio
async def test_mutation_writes_annotation_version(
    migrated_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    dream = await _create_dream(
        migrated_session_factory,
        title="Versioned dream",
        raw_text="A bridge appears over dark water.",
        dream_date=date(2026, 4, 17),
    )
    active_category = await _create_category(
        migrated_session_factory, name=f"active-{uuid.uuid4()}"
    )
    suggested_category = await _create_category(
        migrated_session_factory,
        status="suggested",
        name=f"suggested-{uuid.uuid4()}",
    )
    theme = await _attach_theme(
        migrated_session_factory,
        dream_id=dream.id,
        category_id=active_category.id,
        fragment_text="bridge appears over dark water",
    )

    async with AsyncClient(
        transport=ASGITransport(app=_load_app()),
        base_url="http://testserver",
    ) as client:
        confirm_response = await client.patch(
            f"/dreams/{dream.id}/themes/{theme.id}/confirm",
            headers=_auth_headers(),
        )
        approve_response = await client.patch(
            f"/themes/categories/{suggested_category.id}/approve",
            headers=_auth_headers(),
        )

    assert confirm_response.status_code == 200
    assert approve_response.status_code == 200

    async with migrated_session_factory() as session:
        theme_versions = await session.execute(
            select(AnnotationVersion)
            .where(
                AnnotationVersion.entity_type == "dream_theme",
                AnnotationVersion.entity_id == theme.id,
            )
            .order_by(AnnotationVersion.created_at.asc())
        )
        category_versions = await session.execute(
            select(AnnotationVersion)
            .where(
                AnnotationVersion.entity_type == "theme_category",
                AnnotationVersion.entity_id == suggested_category.id,
            )
            .order_by(AnnotationVersion.created_at.asc())
        )

    theme_version = theme_versions.scalars().all()[-1]
    category_version = category_versions.scalars().all()[-1]

    assert theme_version.snapshot["status_before"] == "draft"
    assert theme_version.snapshot["status_after"] == "confirmed"
    assert theme_version.changed_by == "user"
    assert category_version.snapshot["status_before"] == "suggested"
    assert category_version.snapshot["status_after"] == "active"
    assert category_version.changed_by == "user"

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.api.dreams import read_sync_job_state
from app.models.dream import DreamEntry
from app.retrieval.ingestion import EMBEDDING_DIMENSIONS, fetch_indexed_chunks
from app.services.gdocs_client import GDocsAuthError
from app.workers.index import index_dream
from app.workers.ingest import ingest_document

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _alembic_config() -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    return config


async def _reset_public_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await connection.execute(text("CREATE SCHEMA public"))
        await connection.execute(text("GRANT ALL ON SCHEMA public TO public"))


class FakeRedis:
    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        del ex
        self._values[key] = value
        return True

    async def get(self, key: str) -> str | None:
        return self._values.get(key)


class FailingFirstSyncStatusRedis(FakeRedis):
    def __init__(self) -> None:
        super().__init__()
        self._failed = False

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        if not self._failed and key.startswith("sync_job:"):
            self._failed = True
            raise RuntimeError("transient redis failure")
        return await super().set(key, value, ex=ex)


class StaticGDocsClient:
    def __init__(self, paragraphs: list[str]) -> None:
        self._paragraphs = paragraphs

    def fetch_document(self) -> list[str]:
        return list(self._paragraphs)


class AuthFailingGDocsClient:
    def fetch_document(self) -> list[str]:
        raise GDocsAuthError("Google Docs authentication failed")


class StubEmbeddingClient:
    async def embed(self, texts: list[str], *, dream_id: str | None = None) -> list[list[float]]:
        del dream_id
        return [[0.125] * EMBEDDING_DIMENSIONS for _ in texts]


class RecordingJobEnqueuer:
    def __init__(self) -> None:
        self.calls: list[tuple[uuid.UUID, str]] = []

    async def enqueue_ingest(self, *, job_id: uuid.UUID, doc_id: str) -> None:
        self.calls.append((job_id, doc_id))


def _load_app(
    monkeypatch: pytest.MonkeyPatch,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: FakeRedis,
    job_enqueuer: RecordingJobEnqueuer,
):
    sys.modules.pop("app.api.dreams", None)
    sys.modules.pop("app.main", None)

    from app.shared.config import get_settings

    get_settings.cache_clear()

    import app.api.dreams as dreams_module

    backend = dreams_module.RedisSyncBackend(
        redis_client=redis_client,
        job_enqueuer=job_enqueuer,
        doc_id=os.environ["GOOGLE_DOC_ID"],
    )
    monkeypatch.setattr(dreams_module, "_get_session_factory", lambda: session_factory)
    monkeypatch.setattr(dreams_module, "_get_redis_client", lambda: redis_client)
    monkeypatch.setattr(dreams_module, "_get_job_enqueuer", lambda: job_enqueuer)
    monkeypatch.setattr(dreams_module, "_get_sync_backend", lambda: backend)

    from app.main import app

    return app


@pytest_asyncio.fixture
async def migrated_session_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> async_sessionmaker[AsyncSession]:
    database_url = os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://postgres@localhost:5433/dream_motif_test",
    )
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("REDIS_URL", "redis://test")
    monkeypatch.setenv("GOOGLE_DOC_ID", "doc-workers")
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-google-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-google-client-secret")
    monkeypatch.setenv("GOOGLE_REFRESH_TOKEN", "test-google-refresh-token")

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


def _auth_headers() -> dict[str, str]:
    return {"X-API-Key": os.environ["SECRET_KEY"]}


@pytest.mark.asyncio
async def test_ingest_job_idempotent(
    migrated_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    redis_client = FakeRedis()
    paragraphs = [
        "2026-04-01",
        "I walked through a blue hallway toward a garden.",
    ]
    worker_ctx = {
        "redis": redis_client,
        "session_factory": migrated_session_factory,
        "gdocs_client": StaticGDocsClient(paragraphs),
    }

    first_new_entries = await ingest_document(
        worker_ctx,
        job_id=uuid.uuid4(),
        doc_id="doc-workers",
    )
    second_new_entries = await ingest_document(
        worker_ctx,
        job_id=uuid.uuid4(),
        doc_id="doc-workers",
    )

    async with migrated_session_factory() as session:
        total = await session.scalar(select(func.count()).select_from(DreamEntry))

    assert first_new_entries == 1
    assert second_new_entries == 0
    assert total == 1


@pytest.mark.anyio
async def test_sync_job_status_done_after_completion(
    migrated_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis_client = FakeRedis()
    job_enqueuer = RecordingJobEnqueuer()
    app = _load_app(
        monkeypatch,
        session_factory=migrated_session_factory,
        redis_client=redis_client,
        job_enqueuer=job_enqueuer,
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        queue_response = await client.post("/sync", headers=_auth_headers())

    assert queue_response.status_code == 202
    job_id = uuid.UUID(queue_response.json()["job_id"])
    assert job_enqueuer.calls == [(job_id, "doc-workers")]

    await ingest_document(
        {
            "redis": redis_client,
            "session_factory": migrated_session_factory,
            "gdocs_client": StaticGDocsClient(
                [
                    "2026-04-02",
                    "A silver bridge crossed the river behind the house.",
                ]
            ),
        },
        job_id=job_id,
        doc_id="doc-workers",
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        status_response = await client.get(f"/sync/{job_id}", headers=_auth_headers())

    assert status_response.status_code == 200
    assert status_response.json() == {
        "job_id": str(job_id),
        "status": "done",
        "new_entries": 1,
    }


@pytest.mark.asyncio
async def test_ingest_job_fails_cleanly_on_auth_error(
    migrated_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    redis_client = FakeRedis()
    job_id = uuid.uuid4()

    new_entries = await ingest_document(
        {
            "redis": redis_client,
            "session_factory": migrated_session_factory,
            "gdocs_client": AuthFailingGDocsClient(),
        },
        job_id=job_id,
        doc_id="doc-workers",
    )

    async with migrated_session_factory() as session:
        total = await session.scalar(select(func.count()).select_from(DreamEntry))

    state = await read_sync_job_state(redis_client, job_id)

    assert new_entries == 0
    assert state is not None
    assert state.status == "failed"
    assert state.new_entries is None
    assert total == 0


@pytest.mark.asyncio
async def test_ingest_job_completes_when_initial_status_write_fails(
    migrated_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    redis_client = FailingFirstSyncStatusRedis()
    job_id = uuid.uuid4()

    new_entries = await ingest_document(
        {
            "redis": redis_client,
            "session_factory": migrated_session_factory,
            "gdocs_client": StaticGDocsClient(
                [
                    "2026-04-03",
                    "A paper lantern drifted over the riverbank.",
                ]
            ),
        },
        job_id=job_id,
        doc_id="doc-workers",
    )

    async with migrated_session_factory() as session:
        total = await session.scalar(select(func.count()).select_from(DreamEntry))

    state = await read_sync_job_state(redis_client, job_id)

    assert new_entries == 1
    assert total == 1
    assert state is not None
    assert state.status == "done"
    assert state.new_entries == 1


@pytest.mark.asyncio
async def test_index_worker_idempotent(
    migrated_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with migrated_session_factory() as session:
        dream = DreamEntry(
            source_doc_id="doc-workers",
            date=None,
            title="Worker index dream",
            raw_text="A lantern floated over the river at sunrise.",
            word_count=8,
            content_hash=f"worker-index-{uuid.uuid4()}",
            segmentation_confidence="high",
        )
        session.add(dream)
        await session.commit()

    worker_ctx = {
        "session_factory": migrated_session_factory,
        "embedding_client": StubEmbeddingClient(),
    }
    first_inserted = await index_dream(worker_ctx, dream_id=dream.id)
    second_inserted = await index_dream(worker_ctx, dream_id=dream.id)

    async with migrated_session_factory() as session:
        chunks = await fetch_indexed_chunks(session, dream.id)

    assert first_inserted == 1
    assert second_inserted == 0
    assert len(chunks) == 1

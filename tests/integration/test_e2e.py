from __future__ import annotations

import asyncio
import json
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

from app.api.dreams import SyncJobState, write_sync_job_state
from app.models.annotation import AnnotationVersion
from app.models.dream import DreamChunk, DreamEntry
from app.models.theme import DreamTheme, ThemeCategory
from app.retrieval.ingestion import EMBEDDING_DIMENSIONS, RagIngestionService
from app.retrieval.query import RagQueryService
from app.services.analysis import AnalysisService
from app.services.gdocs_client import GDocsAuthError
from app.workers.ingest import _store_entries

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SEED_DREAMS_PATH = PROJECT_ROOT / "tests" / "fixtures" / "seed_dreams.json"
INTERPRETATION_NOTE = (
    "These theme assignments are computational interpretations, not authoritative conclusions."
)
PATTERN_NOTE = "These are computational patterns, not authoritative interpretations."
PIPELINE_DOC_ID = "doc-e2e"
SEARCH_KEYWORD = "observatory"


def _alembic_config() -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    return config


async def _reset_public_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await connection.execute(text("CREATE SCHEMA public"))
        await connection.execute(text("GRANT ALL ON SCHEMA public TO public"))


async def _rebuild_database(database_url: str) -> None:
    reset_engine = create_async_engine(
        database_url,
        poolclass=NullPool,
        connect_args={"statement_cache_size": 0},
    )
    await _reset_public_schema(reset_engine)
    await reset_engine.dispose()
    await asyncio.to_thread(command.upgrade, _alembic_config(), "head")


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


class SeededGDocsClient:
    def __init__(self, paragraphs: list[str]) -> None:
        self._paragraphs = paragraphs

    def fetch_document(self) -> list[str]:
        return list(self._paragraphs)


class DeterministicEmbeddingClient:
    _FEATURE_TERMS = [
        "water",
        "waves",
        "river",
        "ocean",
        "observatory",
        "labyrinth",
        "shadow",
        "flying",
        "house",
        "rooms",
        "corridor",
        "attic",
        "mirror",
        "train",
        "mother",
        "wolf",
        "snake",
        "bridge",
        "lantern",
        "transformation",
    ]

    async def embed(
        self,
        texts: list[str],
        *,
        dream_id: str | None = None,
    ) -> list[list[float]]:
        del dream_id
        return [self._encode(text) for text in texts]

    def _encode(self, text: str) -> list[float]:
        lowered = text.lower()
        vector = [0.0] * EMBEDDING_DIMENSIONS
        for index, term in enumerate(self._FEATURE_TERMS):
            vector[index] = float(lowered.count(term))
        return vector


class FixtureThemeExtractor:
    _CATEGORY_RULES = (
        (
            "water",
            ("water", "waves", "river", "ocean", "lake", "sea", "flood", "well"),
            0.91,
            "symbolic",
            "Water imagery recurs throughout the entry.",
        ),
        (
            "house_rooms",
            (
                "house",
                "rooms",
                "room",
                "corridor",
                "attic",
                "library",
                "lighthouse",
                "observatory",
                "classroom",
                "hotel",
            ),
            0.82,
            "symbolic",
            "An interior or bounded structure anchors the scene.",
        ),
        (
            "shadow",
            ("shadow", "mirror", "double", "no face", "reflection"),
            0.79,
            "semantic",
            "The entry includes a shadow or double image.",
        ),
        (
            "transformation",
            ("transformation", "wings", "shed", "changed", "change"),
            0.76,
            "semantic",
            "The entry contains an explicit change or metamorphosis cue.",
        ),
        (
            "flying",
            ("fly", "flying", "wings", "sky"),
            0.74,
            "literal",
            "The entry depicts flight or airborne movement.",
        ),
        (
            "separation",
            ("goodbye", "farewell", "departure", "missed", "train"),
            0.71,
            "semantic",
            "The entry carries a departure or separation cue.",
        ),
    )

    async def extract(
        self,
        dream_entry: DreamEntry,
        categories: list[ThemeCategory],
    ):
        category_map = {category.name: category.id for category in categories}
        lowered = dream_entry.raw_text.lower()
        assignments = []

        from app.llm.theme_extractor import ThemeAssignment

        for name, keywords, salience, match_type, justification in self._CATEGORY_RULES:
            if any(keyword in lowered for keyword in keywords):
                assignments.append(
                    ThemeAssignment(
                        category_id=category_map[name],
                        salience=salience,
                        match_type=match_type,
                        justification=justification,
                    )
                )

        if assignments:
            return assignments

        return [
            ThemeAssignment(
                category_id=category_map["inner_child"],
                salience=0.61,
                match_type="semantic",
                justification="Fallback theme for deterministic test coverage.",
            )
        ]


class FixtureGrounder:
    _FRAGMENT_RULES = {
        "water": ["dark water", "water", "waves", "river", "ocean", "lake", "sea", "well"],
        "house_rooms": [
            "observatory",
            "library",
            "lighthouse",
            "house",
            "rooms",
            "room",
            "corridor",
            "attic",
            "classroom",
            "hotel",
        ],
        "shadow": ["shadow", "mirror double", "double", "reflection", "no face"],
        "transformation": ["transformation", "moth wings", "wings", "shed its skin", "changed"],
        "flying": ["could fly", "flying dream", "fly", "cloth wings", "sky bridge"],
        "separation": ["goodbye", "late train", "departure board", "missed a late train"],
        "inner_child": ["childhood"],
    }

    async def ground(self, dream_entry: DreamEntry, theme_assignments):
        from app.llm.grounder import GroundedTheme

        category_names = await self._category_names(theme_assignments)
        grounded = []
        for assignment in theme_assignments:
            category_name = category_names[assignment.category_id]
            fragment = self._build_fragment(
                dream_entry.raw_text, category_name, assignment.match_type
            )
            grounded.append(
                GroundedTheme(
                    category_id=assignment.category_id,
                    salience=assignment.salience,
                    fragments=[fragment],
                )
            )
        return grounded

    async def _category_names(self, theme_assignments) -> dict[uuid.UUID, str]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(ThemeCategory.id, ThemeCategory.name).where(
                    ThemeCategory.id.in_(
                        [assignment.category_id for assignment in theme_assignments]
                    )
                )
            )
        return {row.id: row.name for row in result}

    def bind(self, session_factory: async_sessionmaker[AsyncSession]) -> "FixtureGrounder":
        self._session_factory = session_factory
        return self

    def _build_fragment(
        self, raw_text: str, category_name: str, match_type: str
    ) -> dict[str, object]:
        lowered = raw_text.lower()
        for phrase in self._FRAGMENT_RULES[category_name]:
            start_offset = lowered.find(phrase.lower())
            if start_offset >= 0:
                end_offset = start_offset + len(phrase)
                return {
                    "text": raw_text[start_offset:end_offset],
                    "start_offset": start_offset,
                    "end_offset": end_offset,
                    "match_type": match_type,
                    "verified": True,
                }

        return {
            "text": raw_text[: min(24, len(raw_text))],
            "start_offset": 0,
            "end_offset": min(24, len(raw_text)),
            "match_type": match_type,
            "verified": True,
        }


class PipelineJobEnqueuer:
    def __init__(
        self,
        *,
        redis_client: FakeRedis,
        session_factory: async_sessionmaker[AsyncSession],
        gdocs_client: SeededGDocsClient,
        analysis_service: AnalysisService,
        index_service: RagIngestionService,
    ) -> None:
        self._redis_client = redis_client
        self._session_factory = session_factory
        self._gdocs_client = gdocs_client
        self._analysis_service = analysis_service
        self._index_service = index_service
        self._tasks: set[asyncio.Task[None]] = set()

    async def enqueue_ingest(self, *, job_id: uuid.UUID, doc_id: str) -> None:
        task = asyncio.create_task(self._run_pipeline(job_id=job_id, doc_id=doc_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def wait_for_all(self) -> None:
        if self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def _run_pipeline(self, *, job_id: uuid.UUID, doc_id: str) -> None:
        await write_sync_job_state(self._redis_client, job_id, SyncJobState(status="running"))

        try:
            paragraphs = self._gdocs_client.fetch_document()
            new_entries = await _store_entries(
                session_factory=self._session_factory,
                paragraphs=paragraphs,
                doc_id=doc_id,
            )
            dream_ids = await self._load_dream_ids(doc_id)

            async with self._session_factory() as session:
                for dream_id in dream_ids:
                    await self._analysis_service.analyse_dream(dream_id, session)

            for dream_id in dream_ids:
                await self._index_service.index_dream(dream_id)
        except GDocsAuthError:
            await write_sync_job_state(self._redis_client, job_id, SyncJobState(status="failed"))
            return
        except Exception:
            await write_sync_job_state(self._redis_client, job_id, SyncJobState(status="failed"))
            raise

        await write_sync_job_state(
            self._redis_client,
            job_id,
            SyncJobState(status="done", new_entries=new_entries),
        )

    async def _load_dream_ids(self, doc_id: str) -> list[uuid.UUID]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(DreamEntry.id)
                .where(DreamEntry.source_doc_id == doc_id)
                .order_by(DreamEntry.date.asc(), DreamEntry.created_at.asc())
            )
        return list(result.scalars().all())


def _load_seeded_paragraphs() -> list[str]:
    payload = json.loads(SEED_DREAMS_PATH.read_text(encoding="utf-8"))
    paragraphs: list[str] = []
    for item in payload:
        paragraphs.append(str(item["date"]))
        paragraphs.append(str(item["raw_text"]))
    return paragraphs


def _load_app(
    monkeypatch: pytest.MonkeyPatch,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: FakeRedis,
    job_enqueuer: PipelineJobEnqueuer,
):
    for module_name in (
        "app.api.dreams",
        "app.api.search",
        "app.api.themes",
        "app.api.versioning",
        "app.api.patterns",
        "app.main",
    ):
        sys.modules.pop(module_name, None)

    from app.shared.config import get_settings
    from app.shared.database import get_session_factory

    get_settings.cache_clear()
    get_session_factory.cache_clear()

    import app.api.dreams as dreams_module
    import app.api.search as search_module
    import app.api.themes as themes_module

    backend = dreams_module.RedisSyncBackend(
        redis_client=redis_client,
        job_enqueuer=job_enqueuer,
        doc_id=PIPELINE_DOC_ID,
    )
    monkeypatch.setattr(dreams_module, "_get_redis_client", lambda: redis_client)
    monkeypatch.setattr(dreams_module, "_get_job_enqueuer", lambda: job_enqueuer)
    monkeypatch.setattr(dreams_module, "_get_sync_backend", lambda: backend)
    monkeypatch.setattr(
        search_module,
        "_get_rag_query_service",
        lambda: RagQueryService(
            session_factory=session_factory,
            embedding_client=DeterministicEmbeddingClient(),
        ),
    )
    monkeypatch.setattr(themes_module, "_get_redis_client", lambda: redis_client)

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
    monkeypatch.setenv("GOOGLE_DOC_ID", PIPELINE_DOC_ID)

    await _rebuild_database(database_url)

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


def _build_job_enqueuer(
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: FakeRedis,
) -> PipelineJobEnqueuer:
    grounder = FixtureGrounder().bind(session_factory)
    return PipelineJobEnqueuer(
        redis_client=redis_client,
        session_factory=session_factory,
        gdocs_client=SeededGDocsClient(_load_seeded_paragraphs()),
        analysis_service=AnalysisService(
            theme_extractor=FixtureThemeExtractor(),
            grounder=grounder,
        ),
        index_service=RagIngestionService(
            session_factory=session_factory,
            embedding_client=DeterministicEmbeddingClient(),
        ),
    )


async def _poll_sync_job(client: AsyncClient, job_id: uuid.UUID) -> dict[str, object]:
    for _attempt in range(80):
        response = await client.get(f"/sync/{job_id}", headers=_auth_headers())
        assert response.status_code == 200
        payload = response.json()
        if payload["status"] in {"done", "failed"}:
            return payload
        await asyncio.sleep(0.05)

    raise AssertionError(f"Sync job {job_id} did not finish in time")


async def _cleanup_database_state() -> None:
    database_url = os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://postgres@localhost:5433/dream_motif_test",
    )
    await _rebuild_database(database_url)


async def _count_pipeline_rows(
    session_factory: async_sessionmaker[AsyncSession],
) -> dict[str, int]:
    async with session_factory() as session:
        return {
            "dream_entries": int(
                await session.scalar(select(func.count()).select_from(DreamEntry)) or 0
            ),
            "dream_themes": int(
                await session.scalar(select(func.count()).select_from(DreamTheme)) or 0
            ),
            "dream_chunks": int(
                await session.scalar(select(func.count()).select_from(DreamChunk)) or 0
            ),
            "dream_theme_versions": int(
                await session.scalar(
                    select(func.count())
                    .select_from(AnnotationVersion)
                    .where(AnnotationVersion.entity_type == "dream_theme")
                )
                or 0
            ),
        }


@pytest.mark.anyio
async def test_full_ingestion_to_search_flow(
    migrated_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis_client = FakeRedis()
    job_enqueuer = _build_job_enqueuer(migrated_session_factory, redis_client)
    app = _load_app(
        monkeypatch,
        session_factory=migrated_session_factory,
        redis_client=redis_client,
        job_enqueuer=job_enqueuer,
    )

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            queue_response = await client.post("/sync", headers=_auth_headers())
            assert queue_response.status_code == 202
            job_id = uuid.UUID(queue_response.json()["job_id"])

            status_payload = await _poll_sync_job(client, job_id)
            assert status_payload["status"] == "done"
            assert int(status_payload["new_entries"]) >= 1

            async with migrated_session_factory() as session:
                entry_count = await session.scalar(select(func.count()).select_from(DreamEntry))
                draft_theme_count = await session.scalar(
                    select(func.count()).select_from(DreamTheme).where(DreamTheme.status == "draft")
                )
                observatory_dream = await session.scalar(
                    select(DreamEntry).where(DreamEntry.raw_text.ilike("%observatory%"))
                )
                water_category = await session.scalar(
                    select(ThemeCategory).where(ThemeCategory.name == "water")
                )
                house_rooms_category = await session.scalar(
                    select(ThemeCategory).where(ThemeCategory.name == "house_rooms")
                )
                dream_ids = list(
                    (
                        await session.execute(
                            select(DreamEntry.id).order_by(
                                DreamEntry.date.asc(), DreamEntry.created_at.asc()
                            )
                        )
                    )
                    .scalars()
                    .all()
                )

            assert entry_count is not None and entry_count >= 1
            assert draft_theme_count is not None and draft_theme_count >= 1
            assert observatory_dream is not None
            assert water_category is not None
            assert house_rooms_category is not None

            search_response = await client.get(
                f"/search?q={SEARCH_KEYWORD}",
                headers=_auth_headers(),
            )
            assert search_response.status_code == 200
            search_payload = search_response.json()
            matching_result = next(
                item
                for item in search_payload["results"]
                if item["dream_id"] == str(observatory_dream.id)
            )
            assert matching_result["relevance_score"] > 0.3

            themes_response = await client.get(
                f"/dreams/{observatory_dream.id}/themes",
                headers=_auth_headers(),
            )
            assert themes_response.status_code == 200
            theme_payload = themes_response.json()
            assert theme_payload["dream_id"] == str(observatory_dream.id)
            assert theme_payload["themes"]
            target_theme = theme_payload["themes"][0]
            assert target_theme["status"] == "draft"
            assert target_theme["interpretation_note"] == INTERPRETATION_NOTE

            bulk_confirm_response = await client.post(
                "/curate/bulk-confirm",
                json={"dream_ids": [str(dream_id) for dream_id in dream_ids]},
                headers=_auth_headers(),
            )
            assert bulk_confirm_response.status_code == 200
            bulk_confirm_payload = bulk_confirm_response.json()
            assert bulk_confirm_payload["requires_approval"] is True
            assert bulk_confirm_payload["token"]

            approve_response = await client.post(
                f"/curate/bulk-confirm/{bulk_confirm_payload['token']}/approve",
                headers=_auth_headers(),
            )
            assert approve_response.status_code == 200
            approve_payload = approve_response.json()
            assert approve_payload["confirmed_count"] >= 1

            recurring_response = await client.get(
                "/patterns/recurring",
                headers=_auth_headers(),
            )
            assert recurring_response.status_code == 200
            recurring_payload = recurring_response.json()
            assert recurring_payload["interpretation_note"] == PATTERN_NOTE
            assert any(
                pattern["category_id"] == str(water_category.id)
                for pattern in recurring_payload["patterns"]
            )

            co_occurrence_response = await client.get(
                "/patterns/co-occurrence",
                headers=_auth_headers(),
            )
            assert co_occurrence_response.status_code == 200
            co_occurrence_payload = co_occurrence_response.json()
            assert co_occurrence_payload["interpretation_note"] == PATTERN_NOTE
            assert {
                str(water_category.id),
                str(house_rooms_category.id),
            } in [set(pair["category_ids"]) for pair in co_occurrence_payload["pairs"]]

            timeline_response = await client.get(
                f"/patterns/timeline?theme_id={water_category.id}",
                headers=_auth_headers(),
            )
            assert timeline_response.status_code == 200
            timeline_payload = timeline_response.json()
            assert timeline_payload["interpretation_note"] == PATTERN_NOTE
            assert timeline_payload["timeline"]

            confirmed_themes_response = await client.get(
                f"/dreams/{observatory_dream.id}/themes",
                headers=_auth_headers(),
            )
            assert confirmed_themes_response.status_code == 200
            confirmed_theme = confirmed_themes_response.json()["themes"][0]
            assert confirmed_theme["status"] == "confirmed"

            history_response = await client.get(
                f"/dreams/{observatory_dream.id}/themes/history",
                headers=_auth_headers(),
            )
            assert history_response.status_code == 200
            history_payload = history_response.json()

            async with migrated_session_factory() as session:
                theme_row = await session.scalar(
                    select(DreamTheme)
                    .where(DreamTheme.dream_id == observatory_dream.id)
                    .order_by(DreamTheme.salience.desc(), DreamTheme.created_at.asc())
                )

            assert theme_row is not None
            rollback_version_id = next(
                item["id"]
                for item in history_payload["items"]
                if item["entity_id"] == str(theme_row.id)
                and item["snapshot"]["status_after"] == "confirmed"
            )
            rollback_response = await client.post(
                f"/dreams/{observatory_dream.id}/themes/{theme_row.id}/rollback/{rollback_version_id}",
                headers=_auth_headers(),
            )
            assert rollback_response.status_code == 200
            rollback_payload = rollback_response.json()
            assert rollback_payload["status"] == "draft"
            assert rollback_payload["interpretation_note"] == INTERPRETATION_NOTE

            post_rollback_history = await client.get(
                f"/dreams/{observatory_dream.id}/themes/history",
                headers=_auth_headers(),
            )
            assert post_rollback_history.status_code == 200
            assert len(post_rollback_history.json()["items"]) == len(history_payload["items"]) + 1
    finally:
        await job_enqueuer.wait_for_all()
        await _cleanup_database_state()


@pytest.mark.anyio
async def test_e2e_cleanup_is_complete(
    migrated_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis_client = FakeRedis()
    job_enqueuer = _build_job_enqueuer(migrated_session_factory, redis_client)
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
        status_payload = await _poll_sync_job(client, job_id)
        assert status_payload["status"] == "done"

    await job_enqueuer.wait_for_all()

    counts_before_cleanup = await _count_pipeline_rows(migrated_session_factory)
    assert counts_before_cleanup["dream_entries"] >= 1
    assert counts_before_cleanup["dream_themes"] >= 1
    assert counts_before_cleanup["dream_chunks"] >= 1
    assert counts_before_cleanup["dream_theme_versions"] >= 1

    await _cleanup_database_state()

    counts = await _count_pipeline_rows(migrated_session_factory)
    assert counts == {
        "dream_entries": 0,
        "dream_themes": 0,
        "dream_chunks": 0,
        "dream_theme_versions": 0,
    }

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.gdocs_client import GDocsClient, GoogleDocMetadata
from app.shared.config import get_settings
from app.shared.tracing import get_logger
from app.workers.ingest import ingest_document

logger = get_logger(__name__)


@dataclass(frozen=True)
class AutoSyncState:
    last_seen_marker: str | None = None
    last_checked_at: str | None = None
    last_synced_at: str | None = None
    last_sync_job_id: str | None = None
    last_sync_status: str = "never"


@dataclass(frozen=True)
class AutoSyncResult:
    action: str
    marker: str
    job_id: str | None = None


async def run_auto_sync_once(
    *,
    redis_client: Any,
    session_factory: async_sessionmaker[AsyncSession],
    gdocs_client: GDocsClient | None = None,
) -> AutoSyncResult:
    settings = get_settings()
    if not settings.AUTO_SYNC_ENABLED:
        return AutoSyncResult(action="disabled", marker="")

    client = gdocs_client or GDocsClient(settings=settings)
    metadata = await asyncio.to_thread(client.fetch_document_metadata)
    marker = metadata.change_marker
    state = await read_auto_sync_state(redis_client, metadata.document_id)
    now = _utcnow().isoformat()

    if state.last_seen_marker == marker:
        await write_auto_sync_state(
            redis_client,
            metadata.document_id,
            AutoSyncState(
                last_seen_marker=state.last_seen_marker,
                last_checked_at=now,
                last_synced_at=state.last_synced_at,
                last_sync_job_id=state.last_sync_job_id,
                last_sync_status=state.last_sync_status,
            ),
        )
        return AutoSyncResult(action="no_change", marker=marker, job_id=state.last_sync_job_id)

    job_id = str(uuid.uuid4())
    await write_auto_sync_state(
        redis_client,
        metadata.document_id,
        AutoSyncState(
            last_seen_marker=state.last_seen_marker,
            last_checked_at=now,
            last_synced_at=state.last_synced_at,
            last_sync_job_id=job_id,
            last_sync_status="running",
        ),
    )

    try:
        await ingest_document(
            {
                "redis": redis_client,
                "session_factory": session_factory,
                "gdocs_client": client,
            },
            job_id=uuid.UUID(job_id),
            doc_id=metadata.document_id,
        )
    except Exception:
        await write_auto_sync_state(
            redis_client,
            metadata.document_id,
            AutoSyncState(
                last_seen_marker=state.last_seen_marker,
                last_checked_at=now,
                last_synced_at=state.last_synced_at,
                last_sync_job_id=job_id,
                last_sync_status="failed",
            ),
        )
        raise

    synced_at = _utcnow().isoformat()
    await write_auto_sync_state(
        redis_client,
        metadata.document_id,
        AutoSyncState(
            last_seen_marker=marker,
            last_checked_at=now,
            last_synced_at=synced_at,
            last_sync_job_id=job_id,
            last_sync_status="synced",
        ),
    )
    return AutoSyncResult(action="synced", marker=marker, job_id=job_id)


async def run_auto_sync_loop(
    *,
    redis_client: Any,
    session_factory: async_sessionmaker[AsyncSession],
    gdocs_client: GDocsClient | None = None,
) -> None:
    settings = get_settings()
    if not settings.AUTO_SYNC_ENABLED:
        raise RuntimeError("AUTO_SYNC_ENABLED must be true to start the auto-sync loop")
    if settings.AUTO_SYNC_INTERVAL_SECONDS <= 0:
        raise RuntimeError("AUTO_SYNC_INTERVAL_SECONDS must be greater than zero")

    logger.info("auto_sync.loop_started", interval_seconds=settings.AUTO_SYNC_INTERVAL_SECONDS)
    while True:
        try:
            result = await run_auto_sync_once(
                redis_client=redis_client,
                session_factory=session_factory,
                gdocs_client=gdocs_client,
            )
            logger.info(
                "auto_sync.loop_iteration_completed",
                action=result.action,
                marker=result.marker,
                job_id=result.job_id,
            )
        except Exception:
            logger.exception("auto_sync.loop_iteration_failed")

        await asyncio.sleep(settings.AUTO_SYNC_INTERVAL_SECONDS)


async def read_auto_sync_state(redis_client: Any, document_id: str) -> AutoSyncState:
    payload = await redis_client.get(_auto_sync_key(document_id))
    if payload is None:
        return AutoSyncState()

    data = json.loads(payload)
    return AutoSyncState(
        last_seen_marker=data.get("last_seen_marker"),
        last_checked_at=data.get("last_checked_at"),
        last_synced_at=data.get("last_synced_at"),
        last_sync_job_id=data.get("last_sync_job_id"),
        last_sync_status=str(data.get("last_sync_status") or "never"),
    )


async def write_auto_sync_state(
    redis_client: Any,
    document_id: str,
    state: AutoSyncState,
) -> None:
    await redis_client.set(_auto_sync_key(document_id), json.dumps(asdict(state)))


def build_auto_sync_state_from_metadata(
    metadata: GoogleDocMetadata,
    *,
    last_checked_at: str,
    last_synced_at: str | None,
    last_sync_job_id: str | None,
    last_sync_status: str,
) -> AutoSyncState:
    return AutoSyncState(
        last_seen_marker=metadata.change_marker,
        last_checked_at=last_checked_at,
        last_synced_at=last_synced_at,
        last_sync_job_id=last_sync_job_id,
        last_sync_status=last_sync_status,
    )


def _auto_sync_key(document_id: str) -> str:
    return f"auto_sync:gdocs:{document_id}"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

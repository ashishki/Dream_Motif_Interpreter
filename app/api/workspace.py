"""Task-first single-operator workspace; authenticated by app.main middleware.

No route here is public. The Mini App uses the same archive and durable note
write path as Telegram, not a second storage system or model-generated writes.
"""

from __future__ import annotations

import uuid
import os
from datetime import date
from typing import Literal

from anthropic import AsyncAnthropic

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.assistant.facade import AssistantFacade
from app.assistant.tools import _search_evidence_text
from app.models.dream import DreamEntry
from app.services.archive_research import research_selected_dreams, render_research_report
from app.retrieval.query import RagQueryService
from app.shared.database import get_session_factory
from app.shared.tracing import get_tracer

router = APIRouter(prefix="/workspace")


class ArchiveItem(BaseModel):
    id: uuid.UUID
    date: str | None
    title: str
    preview: str


class ArchivePage(BaseModel):
    items: list[ArchiveItem]
    total: int
    page: int
    next_page: int | None


class ArchiveSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)


class ArchiveSearchResponse(BaseModel):
    items: list[ArchiveItem]
    coverage: Literal["ranked_selection"] = "ranked_selection"
    message: str


class WorkspaceNoteRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    kind: Literal["note", "code"] = "note"


class WorkspaceNoteResponse(BaseModel):
    saved: bool
    message: str
    text: str


def _facade() -> AssistantFacade:
    factory = get_session_factory()
    return AssistantFacade(
        session_factory=factory, rag_query_service=RagQueryService(session_factory=factory)
    )


@router.get("/archive", response_model=ArchivePage)
async def archive_page(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    since: date | None = None,
    until: date | None = None,
) -> ArchivePage:
    if since is not None and until is not None and since > until:
        raise HTTPException(status_code=422, detail="Invalid date range")
    conditions = []
    if since is not None:
        conditions.append(DreamEntry.date >= since)
    if until is not None:
        conditions.append(DreamEntry.date <= until)
    async with get_session_factory()() as session:
        with get_tracer(__name__).start_as_current_span("workspace.archive_page"):
            total = int(
                await session.scalar(
                    select(func.count()).select_from(DreamEntry).where(*conditions)
                )
                or 0
            )
            result = await session.execute(
                select(DreamEntry)
                .where(*conditions)
                .order_by(
                    DreamEntry.date.desc().nulls_last(),
                    DreamEntry.created_at.desc(),
                    DreamEntry.id.desc(),
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            rows = list(result.scalars().all())
    return ArchivePage(
        items=[
            ArchiveItem(
                id=row.id,
                date=row.date.isoformat() if row.date else None,
                title=row.title,
                preview=row.raw_text[:240],
            )
            for row in rows
        ],
        total=total,
        page=page,
        next_page=page + 1 if page * page_size < total else None,
    )


@router.post("/search", response_model=ArchiveSearchResponse)
async def search_archive(payload: ArchiveSearchRequest) -> ArchiveSearchResponse:
    query = payload.query.strip()
    if not query:
        raise HTTPException(status_code=422, detail="Empty query")
    try:
        result = await _facade().search_dreams(query)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Archive search unavailable") from exc
    items = [
        ArchiveItem(
            id=item.dream_id,
            date=str(item.date) if item.date else None,
            title=item.title or "без названия",
            preview=_search_evidence_text(item),
        )
        for item in result.items
    ]
    message = (
        "Найдены подходящие записи. Это подборка по смыслу, не гарантия полного охвата архива."
        if items
        else "Не нашёл достаточно точных совпадений. Попробуйте другой образ или формулировку."
    )
    return ArchiveSearchResponse(items=items, message=message)


@router.get("/dreams/{dream_id}")
async def workspace_dream(dream_id: uuid.UUID) -> dict:
    detail = await _facade().get_dream(dream_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Dream not found")
    # Explicit allowlist: no provider credentials, raw errors or source document IDs.
    return {
        "id": str(detail.id),
        "date": detail.date,
        "title": detail.title,
        "raw_text": detail.raw_text,
        "notes": detail.notes,
    }


@router.post("/dreams/{dream_id}/notes", response_model=WorkspaceNoteResponse)
async def add_workspace_note(
    dream_id: uuid.UUID, payload: WorkspaceNoteRequest
) -> WorkspaceNoteResponse:
    text = payload.text.strip()
    if payload.kind == "code":
        text = " ".join(text.lstrip("#").split())
        if not text or len(text) > 160:
            raise HTTPException(status_code=422, detail="Invalid code label")
        text = "#" + text
    elif not text:
        raise HTTPException(status_code=422, detail="Empty note")
    try:
        # Explicit user action only. Hash-based note identity makes retries safe;
        # canonical note + index/Docs jobs commit together in the existing facade.
        saved, _ = await _facade().add_dream_note(text, dream_id=dream_id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Could not confirm note save") from exc
    if not saved:
        raise HTTPException(status_code=404, detail="Dream not found")
    return WorkspaceNoteResponse(
        saved=True,
        text=text,
        message="Сохранено в заметках к этому сну. Поиск и копия в Google Docs обновляются отдельно.",
    )


class WorkspaceResearchRequest(BaseModel):
    dream_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    question: str = Field(
        default="Что общего и чем различаются эти сны?", min_length=1, max_length=2000
    )


class WorkspaceResearchResponse(BaseModel):
    state: Literal["complete", "partial", "unavailable"]
    requested_count: int
    read_count: int
    answer: str
    source_ids: list[uuid.UUID]
    interpretation_note: Literal[
        "Предложения для проверки, не диагноз и не окончательная интерпретация."
    ] = "Предложения для проверки, не диагноз и не окончательная интерпретация."


@router.post("/research", response_model=WorkspaceResearchResponse)
async def research_workspace_selection(
    payload: WorkspaceResearchRequest,
) -> WorkspaceResearchResponse:
    """An explicit read-only user action; never mutates or codes the archive."""
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        raise HTTPException(status_code=503, detail="Archive research unavailable")
    if not payload.question.strip():
        raise HTTPException(status_code=422, detail="Empty question")
    model = os.environ.get("ASSISTANT_RESEARCH_MODEL") or os.environ.get(
        "ASSISTANT_MODEL", "claude-haiku-4-5-20251001"
    )
    async with AsyncAnthropic(api_key=key, timeout=45, max_retries=1) as client:
        report = await research_selected_dreams(
            _facade(),
            dream_ids=payload.dream_ids,
            question=payload.question.strip(),
            client=client,
            model=model,
        )
    return WorkspaceResearchResponse(
        state=report.state,
        requested_count=report.requested_count,
        read_count=report.loaded_count,
        answer=render_research_report(report),
        source_ids=[uuid.UUID(item.dream_id) for item in report.sources],
    )

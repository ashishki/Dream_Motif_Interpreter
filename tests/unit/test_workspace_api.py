"""Task-first workspace HTTP contracts using authored-synthetic fixtures only."""

from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock, patch, call

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from app.api import workspace
from app.api.workspace import ArchiveSearchRequest, WorkspaceNoteRequest
from app.shared.config import get_settings

ID = uuid.UUID(int=1001)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,path,body",
    [
        ("GET", "/workspace/archive", None),
        ("POST", "/workspace/search", {"query": "мост"}),
        ("GET", f"/workspace/dreams/{ID}", None),
        ("POST", f"/workspace/dreams/{ID}/notes", {"text": "#мост"}),
    ],
)
async def test_workspace_auth_runs_before_data_or_model_access(method, path, body):
    from app.main import app

    with (
        patch.object(workspace, "_facade") as facade,
        patch.object(workspace, "get_session_factory") as db,
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.request(method, path, json=body)
    assert response.status_code == 401
    facade.assert_not_called()
    db.assert_not_called()
    assert "no-store" in response.headers["cache-control"]


@pytest.mark.asyncio
async def test_code_write_is_explicit_and_uses_canonical_note_path():
    from app.main import app

    facade = AsyncMock()
    facade.add_dream_note.return_value = (True, "internal state not forwarded")
    with patch.object(workspace, "_facade", return_value=facade):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                f"/workspace/dreams/{ID}/notes",
                json={"text": "  #  возвращение   домой  ", "kind": "code"},
                headers={"X-API-Key": get_settings().SECRET_KEY},
            )
    assert response.status_code == 200
    assert response.json()["text"] == "#возвращение домой"
    assert response.json()["saved"] is True
    assert "отдельно" in response.json()["message"]
    facade.add_dream_note.assert_awaited_once_with("#возвращение домой", dream_id=ID)
    assert facade.method_calls == [call.add_dream_note("#возвращение домой", dream_id=ID)]


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["#", "   ", "а" * 161])
async def test_invalid_code_never_reaches_persistence(text):
    with patch.object(workspace, "_facade") as facade:
        with pytest.raises(HTTPException) as error:
            await workspace.add_workspace_note(ID, WorkspaceNoteRequest(text=text, kind="code"))
    assert error.value.status_code == 422
    facade.assert_not_called()


@pytest.mark.asyncio
async def test_unknown_note_commit_outcome_is_not_reported_as_success():
    facade = AsyncMock()
    facade.add_dream_note.side_effect = RuntimeError("private payload must not escape")
    with patch.object(workspace, "_facade", return_value=facade):
        with pytest.raises(HTTPException) as error:
            await workspace.add_workspace_note(ID, WorkspaceNoteRequest(text="synthetic note"))
    assert error.value.status_code == 503
    assert "private payload" not in error.value.detail


@pytest.mark.asyncio
async def test_detail_returns_verbatim_text_notes_separate_and_no_source_id():
    raw = "В тексте <дверь> и *звёздочка*.\nВторая строка."
    facade = AsyncMock()
    facade.get_dream.return_value = NS(
        id=ID,
        date="2026-01-01",
        title="Сон",
        raw_text=raw,
        notes=["#мост"],
        source_doc_id="private-doc",
    )
    with patch.object(workspace, "_facade", return_value=facade):
        result = await workspace.workspace_dream(ID)
    assert result["raw_text"] == raw
    assert result["notes"] == ["#мост"]
    assert "source_doc_id" not in result


@pytest.mark.asyncio
async def test_search_uses_verified_evidence_not_untrusted_fallback_text():
    facade = AsyncMock()
    facade.search_dreams.return_value = NS(
        items=[
            NS(
                dream_id=ID,
                date=date(2026, 1, 1),
                title="Мост",
                quote="Я у моста.",
                matched_fragments=[],
                chunk_text="must not replace verified quote",
            )
        ]
    )
    with patch.object(workspace, "_facade", return_value=facade):
        result = await workspace.search_archive(ArchiveSearchRequest(query="  мост  "))
    facade.search_dreams.assert_awaited_once_with("мост")
    assert result.items[0].preview == "Я у моста."
    assert result.coverage == "ranked_selection"
    assert "не гарантия" in result.message


@pytest.mark.asyncio
async def test_archive_paging_is_filtered_ordered_and_parameterized():
    session = AsyncMock()
    session.scalar.return_value = 45
    result = MagicMock()
    result.scalars.return_value.all.return_value = [
        NS(id=ID, date=date(2026, 1, 1), title="Мост", raw_text="Я у моста.")
    ]
    session.execute.return_value = result
    ctx = AsyncMock()
    ctx.__aenter__.return_value = session
    factory = MagicMock(return_value=ctx)
    with patch.object(workspace, "get_session_factory", return_value=factory):
        result = await workspace.archive_page(
            page=2, page_size=20, since=date(2026, 1, 1), until=date(2026, 1, 31)
        )
    assert result.total == 45 and result.next_page == 3
    stmt = session.execute.call_args.args[0].compile(dialect=postgresql.dialect())
    assert "OFFSET" in str(stmt) and "NULLS LAST" in str(stmt)
    assert 20 in stmt.params.values()
    assert date(2026, 1, 1) in stmt.params.values()
    assert "2026-01-01" not in str(stmt)


@pytest.mark.asyncio
async def test_inverted_period_does_not_query_database():
    with patch.object(workspace, "get_session_factory") as factory:
        with pytest.raises(HTTPException):
            await workspace.archive_page(
                page=1, page_size=20, since=date(2026, 2, 1), until=date(2026, 1, 1)
            )
    factory.assert_not_called()


@pytest.mark.asyncio
async def test_research_is_authorized_before_model_instantiation():
    from app.main import app

    with patch.object(workspace, "AsyncAnthropic") as model:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            result = await client.post("/workspace/research", json={"dream_ids": [str(ID)]})
    assert result.status_code == 401
    model.assert_not_called()


@pytest.mark.asyncio
async def test_private_request_input_is_not_echoed_in_validation_errors():
    from app.main import app

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/workspace/dreams/{ID}/notes",
            json={"text": "sensitive fixture " * 400},
            headers={"X-API-Key": get_settings().SECRET_KEY},
        )
    assert response.status_code == 422
    assert "sensitive fixture" not in response.text
    assert "no-store" in response.headers["cache-control"]


@pytest.mark.asyncio
async def test_research_response_preserves_partial_coverage_and_closes_client():
    from app.services.archive_research import ArchiveResearchReport, SourceLabel

    report = ArchiveResearchReport(
        requested_count=2, sources=[SourceLabel(str(ID), "2026-01-01", "Мост")], state="partial"
    )
    facade, provider = AsyncMock(), AsyncMock()
    with (
        patch.object(workspace, "_facade", return_value=facade),
        patch.object(workspace, "AsyncAnthropic", return_value=provider),
        patch.object(
            workspace, "research_selected_dreams", new_callable=AsyncMock, return_value=report
        ) as run,
    ):
        result = await workspace.research_workspace_selection(
            workspace.WorkspaceResearchRequest(
                dream_ids=[ID, uuid.UUID(int=1002)], question="Сравни"
            )
        )
    assert result.state == "partial" and result.read_count == 1 and result.requested_count == 2
    assert result.source_ids == [ID] and "1 из 2" in result.answer
    assert "Предложения" in result.interpretation_note
    assert run.await_args.kwargs["question"] == "Сравни"
    provider.__aexit__.assert_awaited_once()
    facade.add_dream_note.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_research_key_is_honest_unavailable(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with patch.object(workspace, "_facade") as reader:
        with pytest.raises(HTTPException) as error:
            await workspace.research_workspace_selection(
                workspace.WorkspaceResearchRequest(dream_ids=[ID])
            )
    assert error.value.status_code == 503
    reader.assert_not_called()

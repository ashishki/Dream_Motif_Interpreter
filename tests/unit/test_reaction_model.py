from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.reaction import MessageReaction
from app.services.reaction_feedback import ReactionFeedbackService
from app.shared.config import ReactionFeedbackMeaning


def test_message_reaction_tablename() -> None:
    assert MessageReaction.__tablename__ == "message_reactions"


def test_reaction_feedback_meaning_rejects_invalid_score() -> None:
    with pytest.raises(ValueError, match="between 1 and 5"):
        ReactionFeedbackMeaning(label="bad", prompt_hint="ignore", score=6)


@pytest.mark.asyncio
async def test_reaction_feedback_context_maps_known_active_reaction() -> None:
    created_at = datetime(2026, 5, 2, tzinfo=timezone.utc)
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [
        SimpleNamespace(emoji="👍", created_at=created_at, removed_at=None)
    ]
    session.execute = AsyncMock(return_value=result)
    service = ReactionFeedbackService(
        mapping={
            "👍": ReactionFeedbackMeaning(
                label="helpful",
                prompt_hint="The response was useful.",
                score=5,
            )
        }
    )

    rows = await service.get_recent_for_context(session)

    assert rows == [
        {
            "source": "telegram_reaction",
            "emoji": "👍",
            "label": "helpful",
            "score": 5,
            "comment": "The response was useful.",
            "created_at": created_at,
        }
    ]
    compiled = str(session.execute.await_args.args[0])
    assert "message_reactions.removed_at IS NULL" in compiled


@pytest.mark.asyncio
async def test_reaction_feedback_context_ignores_unmapped_rows_returned_by_session() -> None:
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [
        SimpleNamespace(
            emoji="🔥",
            created_at=datetime(2026, 5, 2, tzinfo=timezone.utc),
            removed_at=None,
        )
    ]
    session.execute = AsyncMock(return_value=result)
    service = ReactionFeedbackService(
        mapping={
            "👍": ReactionFeedbackMeaning(
                label="helpful",
                prompt_hint="The response was useful.",
            )
        }
    )

    rows = await service.get_recent_for_context(session)

    assert rows == []


@pytest.mark.asyncio
async def test_reaction_feedback_context_returns_recent_rows_oldest_first() -> None:
    older = datetime(2026, 5, 1, tzinfo=timezone.utc)
    newer = datetime(2026, 5, 2, tzinfo=timezone.utc)
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [
        SimpleNamespace(emoji="👍", created_at=newer, removed_at=None),
        SimpleNamespace(emoji="👍", created_at=older, removed_at=None),
    ]
    session.execute = AsyncMock(return_value=result)
    service = ReactionFeedbackService(
        mapping={
            "👍": ReactionFeedbackMeaning(
                label="helpful",
                prompt_hint="The response was useful.",
            )
        }
    )

    rows = await service.get_recent_for_context(session)

    assert [row["created_at"] for row in rows] == [older, newer]
    compiled = str(session.execute.await_args.args[0])
    assert "ORDER BY message_reactions.created_at DESC" in compiled


@pytest.mark.asyncio
async def test_reaction_feedback_context_returns_empty_without_mapping() -> None:
    session = AsyncMock()

    rows = await ReactionFeedbackService(mapping={}).get_recent_for_context(session)

    assert rows == []
    session.execute.assert_not_called()

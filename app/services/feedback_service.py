from __future__ import annotations

import inspect
import logging

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.feedback import AssistantFeedback

LOGGER = logging.getLogger(__name__)


class FeedbackService:
    async def record(
        self,
        chat_id: str,
        score: int,
        context: dict,
        session: AsyncSession,
        comment: str | None = None,
    ) -> AssistantFeedback:
        if score < 1 or score > 5:
            raise ValueError("score must be between 1 and 5")

        feedback = AssistantFeedback(
            chat_id=chat_id,
            score=score,
            context=context,
            comment=comment,
        )
        session.add(feedback)
        return feedback

    async def get_recent_for_context(
        self,
        session: AsyncSession,
        limit: int = 20,
    ) -> list[dict]:
        """Return recent feedback rows suitable for system prompt injection."""
        try:
            stmt = (
                select(
                    AssistantFeedback.score,
                    AssistantFeedback.comment,
                    AssistantFeedback.created_at,
                )
                .where(
                    or_(
                        and_(
                            AssistantFeedback.comment.isnot(None),
                            AssistantFeedback.comment != "",
                        ),
                        AssistantFeedback.score <= 2,
                    )
                )
                .order_by(AssistantFeedback.created_at.asc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            rows = result.all()
            if inspect.isawaitable(rows):
                rows = await rows
            return [
                {
                    "score": row.score,
                    "comment": row.comment,
                    "created_at": row.created_at,
                }
                for row in rows
            ]
        except Exception:
            LOGGER.warning("Failed to load recent feedback for context", exc_info=True)
            return []

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.feedback import AssistantFeedback


class FeedbackService:
    async def record(
        self,
        chat_id: str,
        score: int,
        context: dict,
        session: AsyncSession,
    ) -> AssistantFeedback:
        if score < 1 or score > 5:
            raise ValueError("score must be between 1 and 5")

        feedback = AssistantFeedback(chat_id=chat_id, score=score, context=context)
        session.add(feedback)
        return feedback

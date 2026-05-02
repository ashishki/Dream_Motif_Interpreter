from __future__ import annotations

import inspect
import logging
from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reaction import MessageReaction
from app.shared.config import ReactionFeedbackMeaning, get_settings

LOGGER = logging.getLogger(__name__)


class ReactionFeedbackService:
    def __init__(
        self,
        mapping: Mapping[str, ReactionFeedbackMeaning] | None = None,
    ) -> None:
        self._mapping = dict(mapping) if mapping is not None else None

    @property
    def mapping(self) -> dict[str, ReactionFeedbackMeaning]:
        if self._mapping is not None:
            return self._mapping
        return dict(get_settings().TELEGRAM_REACTION_FEEDBACK_MAPPING)

    async def get_recent_for_context(
        self,
        session: AsyncSession,
        limit: int = 20,
    ) -> list[dict]:
        """Return mapped active Telegram reactions for assistant prompt context."""
        mapping = self.mapping
        if not mapping:
            return []

        try:
            stmt = (
                select(MessageReaction)
                .where(
                    MessageReaction.removed_at.is_(None),
                    MessageReaction.emoji.in_(list(mapping)),
                )
                .order_by(MessageReaction.created_at.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            reactions = result.scalars().all()
            if inspect.isawaitable(reactions):
                reactions = await reactions

            rows: list[dict] = []
            recent_reactions = sorted(
                reactions,
                key=lambda reaction: reaction.created_at,
            )[-limit:]
            for reaction in recent_reactions:
                meaning = mapping.get(reaction.emoji)
                if meaning is None:
                    continue
                rows.append(
                    {
                        "source": "telegram_reaction",
                        "emoji": reaction.emoji,
                        "label": meaning.label,
                        "score": meaning.score,
                        "comment": meaning.prompt_hint,
                        "created_at": reaction.created_at,
                    }
                )
            return rows
        except Exception:
            LOGGER.warning("Failed to load recent reaction feedback for context", exc_info=True)
            return []

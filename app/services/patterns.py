from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.dream import DreamEntry
from app.models.theme import DreamTheme, ThemeCategory
from app.shared.tracing import get_tracer


@dataclass(frozen=True)
class RecurringPattern:
    category_id: uuid.UUID
    name: str
    count: int
    percentage_of_dreams: float


@dataclass(frozen=True)
class CoOccurrencePattern:
    category_ids: tuple[uuid.UUID, uuid.UUID]
    count: int


@dataclass(frozen=True)
class TimelinePoint:
    date: str
    salience: float


class PatternService:
    @staticmethod
    async def list_recurring_patterns(session: AsyncSession) -> list[RecurringPattern]:
        tracer = get_tracer(__name__)

        confirmed_theme_dreams = (
            select(DreamTheme.category_id, DreamTheme.dream_id)
            .where(
                DreamTheme.status == "confirmed",
                DreamTheme.deprecated.is_(False),
            )
            .distinct()
            .subquery()
        )

        with tracer.start_as_current_span("db.query.patterns.recurring.total_dreams"):
            total_confirmed_dreams = await session.scalar(
                select(func.count(func.distinct(confirmed_theme_dreams.c.dream_id)))
            )

        with tracer.start_as_current_span("db.query.patterns.recurring.patterns"):
            result = await session.execute(
                select(
                    ThemeCategory.id,
                    ThemeCategory.name,
                    func.count().label("count"),
                )
                .join(
                    confirmed_theme_dreams,
                    confirmed_theme_dreams.c.category_id == ThemeCategory.id,
                )
                .group_by(ThemeCategory.id, ThemeCategory.name)
                .order_by(func.count().desc(), ThemeCategory.name.asc())
            )

        denominator = int(total_confirmed_dreams or 0)
        patterns: list[RecurringPattern] = []
        for category_id, name, count in result.all():
            pattern_count = int(count)
            patterns.append(
                RecurringPattern(
                    category_id=category_id,
                    name=name,
                    count=pattern_count,
                    percentage_of_dreams=(
                        round(pattern_count / denominator, 4) if denominator > 0 else 0.0
                    ),
                )
            )
        return patterns

    @staticmethod
    async def list_co_occurrence_patterns(session: AsyncSession) -> list[CoOccurrencePattern]:
        tracer = get_tracer(__name__)

        distinct_confirmed_themes = (
            select(DreamTheme.dream_id, DreamTheme.category_id)
            .where(
                DreamTheme.status == "confirmed",
                DreamTheme.deprecated.is_(False),
            )
            .distinct()
            .subquery()
        )
        left_theme = aliased(distinct_confirmed_themes)
        right_theme = aliased(distinct_confirmed_themes)

        with tracer.start_as_current_span("db.query.patterns.co_occurrence"):
            result = await session.execute(
                select(
                    left_theme.c.category_id,
                    right_theme.c.category_id,
                    func.count().label("count"),
                )
                .select_from(left_theme)
                .join(
                    right_theme,
                    and_(
                        left_theme.c.dream_id == right_theme.c.dream_id,
                        left_theme.c.category_id < right_theme.c.category_id,
                    ),
                )
                .group_by(left_theme.c.category_id, right_theme.c.category_id)
                .having(func.count() >= 2)
                .order_by(func.count().desc())
            )

        return [
            CoOccurrencePattern(
                category_ids=(left_category_id, right_category_id),
                count=int(count),
            )
            for left_category_id, right_category_id, count in result.all()
        ]

    @staticmethod
    async def get_theme_timeline(
        session: AsyncSession,
        *,
        category_id: uuid.UUID,
    ) -> list[TimelinePoint]:
        tracer = get_tracer(__name__)

        with tracer.start_as_current_span("db.query.patterns.timeline"):
            result = await session.execute(
                select(DreamEntry.date, DreamTheme.salience)
                .join(DreamTheme, DreamTheme.dream_id == DreamEntry.id)
                .where(
                    DreamTheme.category_id == category_id,
                    DreamTheme.status == "confirmed",
                    DreamTheme.deprecated.is_(False),
                    DreamEntry.date.is_not(None),
                )
                .order_by(DreamEntry.date.asc(), DreamTheme.created_at.asc())
            )

        return [
            TimelinePoint(date=dream_date.isoformat(), salience=salience)
            for dream_date, salience in result.all()
        ]

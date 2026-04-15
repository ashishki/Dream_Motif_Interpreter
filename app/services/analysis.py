from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.llm.grounder import GroundedTheme, Grounder
from app.llm.theme_extractor import ThemeAssignment, ThemeExtractor
from app.models.dream import DreamEntry
from app.models.theme import DreamTheme, ThemeCategory
from app.shared.tracing import get_tracer
from app.services.versioning import (
    build_dream_theme_creation_version,
    build_dream_theme_update_version,
)


class AnalysisService:
    def __init__(
        self,
        *,
        theme_extractor: ThemeExtractor | None = None,
        grounder: Grounder | None = None,
    ) -> None:
        self._theme_extractor = theme_extractor or ThemeExtractor()
        self._grounder = grounder or Grounder()

    async def analyse_dream(
        self,
        dream_id: uuid.UUID,
        session: AsyncSession,
    ) -> list[ThemeAssignment]:
        tracer = get_tracer(__name__)

        with tracer.start_as_current_span("analysis.analyse_dream"):
            with tracer.start_as_current_span("db.query.analysis.load_dream"):
                dream_entry = await session.get(DreamEntry, dream_id)
            if dream_entry is None:
                raise ValueError(f"Dream entry {dream_id} does not exist")

            with tracer.start_as_current_span("db.query.analysis.load_categories"):
                categories_result = await session.execute(
                    select(ThemeCategory)
                    .where(ThemeCategory.status == "active")
                    .order_by(ThemeCategory.created_at.asc())
                )
            categories = list(categories_result.scalars().all())
            assignments = await self._theme_extractor.extract(dream_entry, categories)
            grounded_themes = await self._grounder.ground(dream_entry, assignments)
            grounded_by_category = {
                grounded_theme.category_id: grounded_theme for grounded_theme in grounded_themes
            }

            with tracer.start_as_current_span("db.query.analysis.load_existing_themes"):
                existing_result = await session.execute(
                    select(DreamTheme).where(DreamTheme.dream_id == dream_entry.id)
                )
            existing_themes = {
                theme.category_id: theme for theme in existing_result.scalars().all()
            }

            for assignment in assignments:
                grounded_theme = grounded_by_category.get(
                    assignment.category_id,
                    GroundedTheme(
                        category_id=assignment.category_id,
                        salience=assignment.salience,
                        fragments=[],
                    ),
                )
                existing_theme = existing_themes.get(assignment.category_id)

                if existing_theme is None:
                    dream_theme_id = uuid.uuid4()
                    session.add(
                        build_dream_theme_creation_version(
                            theme_id=dream_theme_id,
                            dream_id=dream_entry.id,
                            category_id=assignment.category_id,
                            salience=grounded_theme.salience,
                            status="draft",
                            match_type=assignment.match_type,
                            fragments=grounded_theme.fragments,
                            deprecated=False,
                            changed_by="system",
                        )
                    )
                    session.add(
                        DreamTheme(
                            id=dream_theme_id,
                            dream_id=dream_entry.id,
                            category_id=assignment.category_id,
                            salience=grounded_theme.salience,
                            status="draft",
                            match_type=assignment.match_type,
                            fragments=grounded_theme.fragments,
                            deprecated=False,
                        )
                    )
                    continue

                session.add(
                    build_dream_theme_update_version(
                        theme=existing_theme,
                        next_salience=grounded_theme.salience,
                        next_match_type=assignment.match_type,
                        next_fragments=grounded_theme.fragments,
                        changed_by="system",
                    )
                )
                existing_theme.salience = grounded_theme.salience
                existing_theme.match_type = assignment.match_type
                existing_theme.fragments = grounded_theme.fragments

            with tracer.start_as_current_span("db.query.analysis.commit"):
                await session.commit()
            return assignments

    async def analyse_dream_with_session_factory(
        self,
        dream_id: uuid.UUID,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> list[ThemeAssignment]:
        async with session_factory() as session:
            return await self.analyse_dream(dream_id, session)

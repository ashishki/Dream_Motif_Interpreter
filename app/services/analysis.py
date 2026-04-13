from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.grounder import GroundedTheme, Grounder
from app.llm.theme_extractor import ThemeAssignment, ThemeExtractor
from app.models.annotation import AnnotationVersion
from app.models.dream import DreamEntry
from app.models.theme import DreamTheme, ThemeCategory
from app.shared.tracing import get_tracer


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
                        AnnotationVersion(
                            entity_type="dream_theme",
                            entity_id=dream_theme_id,
                            snapshot={
                                "entity_type": "dream_theme",
                                "entity_id": str(dream_theme_id),
                                "dream_id": str(dream_entry.id),
                                "category_id": str(assignment.category_id),
                                "status_before": None,
                                "status_after": "draft",
                                "changed_by": "system",
                            },
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
                    AnnotationVersion(
                        entity_type="dream_theme",
                        entity_id=existing_theme.id,
                        snapshot={
                            "entity_type": "dream_theme",
                            "entity_id": str(existing_theme.id),
                            "dream_id": str(existing_theme.dream_id),
                            "category_id": str(existing_theme.category_id),
                            "status_before": existing_theme.status,
                            "status_after": existing_theme.status,
                            "salience_before": existing_theme.salience,
                            "match_type_before": existing_theme.match_type,
                            "fragments_before": existing_theme.fragments,
                            "deprecated_before": existing_theme.deprecated,
                            "changed_by": "system",
                        },
                        changed_by="system",
                    )
                )
                existing_theme.salience = grounded_theme.salience
                existing_theme.match_type = assignment.match_type
                existing_theme.fragments = grounded_theme.fragments

            with tracer.start_as_current_span("db.query.analysis.commit"):
                await session.commit()
            return assignments

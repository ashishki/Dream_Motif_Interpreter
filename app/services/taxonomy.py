from __future__ import annotations

import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.annotation import AnnotationVersion
from app.models.theme import ThemeCategory
from app.shared.tracing import get_tracer


class TaxonomyService:
    @staticmethod
    async def create_category(
        session: AsyncSession,
        name: str,
        description: str | None,
    ) -> uuid.UUID:
        tracer = get_tracer(__name__)
        category_id = uuid.uuid4()

        with tracer.start_as_current_span("taxonomy.create_category"):
            session.add(
                AnnotationVersion(
                    entity_type="theme_category",
                    entity_id=category_id,
                    snapshot={
                        "entity_type": "theme_category",
                        "entity_id": str(category_id),
                        "status_before": None,
                        "status_after": "suggested",
                        "changed_by": "system",
                    },
                    changed_by="system",
                )
            )
            session.add(
                ThemeCategory(
                    id=category_id,
                    name=name,
                    description=description,
                    status="suggested",
                )
            )
            with tracer.start_as_current_span("db.query.taxonomy.commit_create_category"):
                await session.commit()

        return category_id

    @staticmethod
    async def approve_category(session: AsyncSession, category_id: uuid.UUID) -> None:
        await TaxonomyService._transition_category(
            session=session,
            category_id=category_id,
            from_status="suggested",
            to_status="active",
        )

    @staticmethod
    async def deprecate_category(session: AsyncSession, category_id: uuid.UUID) -> None:
        await TaxonomyService._transition_category(
            session=session,
            category_id=category_id,
            from_status="active",
            to_status="deprecated",
            update_dream_themes=True,
        )

    @staticmethod
    async def _transition_category(
        session: AsyncSession,
        category_id: uuid.UUID,
        from_status: str,
        to_status: str,
        *,
        update_dream_themes: bool = False,
    ) -> None:
        tracer = get_tracer(__name__)

        with tracer.start_as_current_span("taxonomy.transition_category"):
            with tracer.start_as_current_span("db.query.taxonomy.load_category"):
                result = await session.execute(
                    select(ThemeCategory).where(ThemeCategory.id == category_id)
                )
            category = result.scalar_one_or_none()

            if category is None:
                raise ValueError(f"Theme category {category_id} does not exist")
            if category.status != from_status:
                raise ValueError(
                    f"Theme category {category_id} must be {from_status}, got {category.status}"
                )

            session.add(
                AnnotationVersion(
                    entity_type="theme_category",
                    entity_id=category_id,
                    snapshot={
                        "entity_type": "theme_category",
                        "entity_id": str(category_id),
                        "status_before": category.status,
                        "status_after": to_status,
                        "changed_by": "system",
                    },
                    changed_by="system",
                )
            )
            category.status = to_status

            if update_dream_themes:
                with tracer.start_as_current_span("db.query.taxonomy.deprecate_dream_themes"):
                    await session.execute(
                        text(
                            """
                            UPDATE dream_themes
                            SET deprecated = true
                            WHERE category_id = :category_id
                            """
                        ),
                        {"category_id": category_id},
                    )

            with tracer.start_as_current_span("db.query.taxonomy.commit_transition"):
                await session.commit()

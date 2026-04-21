from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.client import AnthropicLLMClient
from app.models.motif import MotifInduction
from app.models.research import ResearchResult
from app.research.retriever import ResearchRetriever
from app.research.synthesizer import ResearchSynthesizer
from app.shared.config import get_settings

logger = logging.getLogger(__name__)

_TRANSLATE_MODEL = "claude-haiku-4-5-20251001"


class ResearchService:
    """Run the research augmentation pipeline for a confirmed motif."""

    def __init__(
        self,
        *,
        retriever: ResearchRetriever | None = None,
        synthesizer: ResearchSynthesizer | None = None,
    ) -> None:
        if retriever is None:
            settings = get_settings()
            retriever = ResearchRetriever(
                settings.RESEARCH_API_BASE_URL,
                settings.RESEARCH_API_KEY,
            )
        self._retriever = retriever
        self._synthesizer = synthesizer or ResearchSynthesizer()

    async def run(
        self,
        motif_id: UUID,
        session: AsyncSession,
        triggered_by: str,
    ) -> ResearchResult:
        result = await session.execute(select(MotifInduction).where(MotifInduction.id == motif_id))
        motif = result.scalar_one_or_none()

        if motif is None:
            raise ValueError(f"Motif {motif_id} not found")

        search_query = await self._build_search_query(motif.label)
        sources = await self._retriever.retrieve(search_query)
        parallels = await self._synthesizer.synthesize(motif.label, sources)

        research_result = ResearchResult(
            motif_id=motif.id,
            dream_id=motif.dream_id,
            query_label=motif.label,
            parallels=parallels,
            sources=sources,
            triggered_by=triggered_by,
        )
        session.add(research_result)
        return research_result

    async def _build_search_query(self, label: str) -> str:
        try:
            client = AnthropicLLMClient(model=_TRANSLATE_MODEL)
            english = await client.complete(
                "Translate this dream motif label to English. Return only the translation, no explanation.",
                label,
                max_tokens=50,
            )
            return f"{english.strip()} dream symbol archetype mythology"
        except Exception:
            logger.warning("research_service.translation_failed", exc_info=True)
            return f"{label} dream symbol archetype mythology"

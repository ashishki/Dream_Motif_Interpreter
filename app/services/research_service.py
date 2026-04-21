from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.motif import MotifInduction
from app.models.research import ResearchResult
from app.research.retriever import ResearchRetriever
from app.research.synthesizer import ResearchSynthesizer
from app.shared.config import get_settings


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
        if motif.status != "confirmed":
            raise ValueError("Research can only be run for confirmed motifs")

        sources = await self._retriever.retrieve(motif.label)
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

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dream import DreamEntry
from app.models.motif import MotifInduction
from app.services.imagery import ImageryExtractionError, ImageryExtractor
from app.services.motif_grounder import MotifGrounder
from app.services.motif_inductor import MotifCandidate, MotifInductionError, MotifInductor
from app.shared.tracing import get_logger, get_tracer

_MODEL_VERSION = "claude-sonnet-4-6"

logger = get_logger(__name__)


class MotifService:
    """Orchestrates the three-stage motif induction pipeline.

    Pipeline order:
      1. ImageryExtractor — extract grounded imagery fragments from raw text
      2. MotifInductor    — form abstract motif candidates from imagery
      3. MotifGrounder    — verify fragment offsets against source text
      4. Persist one MotifInduction row per candidate with status='draft'

    This service NEVER writes to dream_themes.
    """

    def __init__(
        self,
        *,
        imagery_extractor: ImageryExtractor | None = None,
        motif_inductor: MotifInductor | None = None,
        motif_grounder: MotifGrounder | None = None,
    ) -> None:
        self._imagery_extractor = imagery_extractor or ImageryExtractor()
        self._motif_inductor = motif_inductor or MotifInductor()
        self._motif_grounder = motif_grounder or MotifGrounder()

    async def run(self, dream_entry: DreamEntry, session: AsyncSession) -> None:
        """Run the full motif induction pipeline for *dream_entry*.

        Results are persisted to motif_inductions with status='draft'.
        If ImageryExtractor or MotifInductor fails, a structured warning is
        logged and the method returns without crashing the ingest job.

        Args:
            dream_entry: the DreamEntry ORM object to process.
            session: an open async DB session (caller is responsible for commit).
        """
        tracer = get_tracer(__name__)
        dream_id = dream_entry.id

        with tracer.start_as_current_span("motif_service.run") as span:
            span.set_attribute("dream_id", str(dream_id))

            with tracer.start_as_current_span("db.query.motif_service.idempotency_check"):
                existing_result = await session.execute(
                    select(MotifInduction.id).where(MotifInduction.dream_id == dream_id).limit(1)
                )
            if existing_result.scalar_one_or_none() is not None:
                return

            # Stage 1: extract imagery fragments
            try:
                with tracer.start_as_current_span("motif_service.extract_imagery"):
                    fragments = await self._imagery_extractor.extract(dream_entry.raw_text)
            except (ImageryExtractionError, Exception) as exc:
                logger.warning(
                    "motif_service.imagery_extraction_failed",
                    dream_id=str(dream_id),
                    exc_info=True,
                    error=str(exc),
                )
                return

            if not fragments:
                logger.warning(
                    "motif_service.no_imagery_fragments",
                    dream_id=str(dream_id),
                )
                return

            # Stage 2: induce motif candidates
            try:
                with tracer.start_as_current_span("motif_service.induce_motifs"):
                    candidates: list[MotifCandidate] = await self._motif_inductor.induce(fragments)
            except (MotifInductionError, Exception) as exc:
                logger.warning(
                    "motif_service.motif_induction_failed",
                    dream_id=str(dream_id),
                    exc_info=True,
                    error=str(exc),
                )
                return

            if not candidates:
                logger.warning(
                    "motif_service.no_motif_candidates",
                    dream_id=str(dream_id),
                )
                return

            # Stage 3: ground each candidate's fragments and persist
            with tracer.start_as_current_span("motif_service.persist"):
                for candidate in candidates:
                    # Collect imagery fragments referenced by this candidate
                    candidate_fragments = [
                        fragments[idx]
                        for idx in candidate["imagery_indices"]
                        if 0 <= idx < len(fragments)
                    ]

                    # Verify offsets against source text
                    verified_fragments = self._motif_grounder.ground(
                        dream_entry.raw_text, list(candidate_fragments)
                    )

                    row = MotifInduction(
                        dream_id=dream_id,
                        label=candidate["label"],
                        rationale=candidate["rationale"],
                        confidence=candidate["confidence"],
                        status="draft",
                        fragments=verified_fragments,
                        model_version=_MODEL_VERSION,
                    )
                    session.add(row)

            logger.info(
                "motif_service.run_complete",
                dream_id=str(dream_id),
                motif_count=len(candidates),
            )

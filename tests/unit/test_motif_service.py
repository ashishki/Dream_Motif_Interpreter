"""Unit tests for MotifService (WS-9.4).

All tests use stub implementations of ImageryExtractor, MotifInductor,
and MotifGrounder — no real LLM or DB calls are made.

AC-1: MotifService calls ImageryExtractor → MotifInductor → MotifGrounder in order.
AC-2: MotifService writes MotifInduction rows with status='draft' and correct model_version.
AC-3/AC-4: (flag behaviour tested in test_ingest_motif_flag.py via ingest.py)
AC-5: MotifService does NOT write to dream_themes.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.imagery import ImageryExtractionError, ImageryFragment
from app.services.motif_inductor import MotifCandidate, MotifInductionError
from app.services.motif_service import MotifService, _MODEL_VERSION

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

DREAM_TEXT = (
    "I climbed crumbling stairs in a dark tower. "
    "At the top a locked door blocked my way. "
    "My feet kept sinking into the floor."
)


def _make_dream_entry(raw_text: str = DREAM_TEXT) -> Any:
    """Return a minimal DreamEntry-like object."""
    entry = MagicMock()
    entry.id = uuid.uuid4()
    entry.raw_text = raw_text
    return entry


def _make_fragments() -> list[ImageryFragment]:
    text1 = "crumbling stairs"
    start1 = DREAM_TEXT.index(text1)
    text2 = "locked door"
    start2 = DREAM_TEXT.index(text2)
    return [
        ImageryFragment(text=text1, start_offset=start1, end_offset=start1 + len(text1)),
        ImageryFragment(text=text2, start_offset=start2, end_offset=start2 + len(text2)),
    ]


def _make_candidates() -> list[MotifCandidate]:
    return [
        MotifCandidate(
            label="obstructed vertical movement",
            rationale="Stairs and locked door both impede upward progress.",
            confidence="high",
            imagery_indices=[0, 1],
        ),
    ]


class _StubImageryExtractor:
    def __init__(
        self, fragments: list[ImageryFragment], *, raise_exc: Exception | None = None
    ) -> None:
        self._fragments = fragments
        self._raise = raise_exc
        self.call_count = 0

    async def extract(self, dream_text: str) -> list[ImageryFragment]:  # noqa: ARG002
        self.call_count += 1
        if self._raise is not None:
            raise self._raise
        return self._fragments


class _StubMotifInductor:
    def __init__(
        self, candidates: list[MotifCandidate], *, raise_exc: Exception | None = None
    ) -> None:
        self._candidates = candidates
        self._raise = raise_exc
        self.call_count = 0

    async def induce(self, fragments: list[ImageryFragment]) -> list[MotifCandidate]:  # noqa: ARG002
        self.call_count += 1
        if self._raise is not None:
            raise self._raise
        return self._candidates


class _StubMotifGrounder:
    def __init__(self) -> None:
        self.call_count = 0
        self.last_fragments: list[Any] = []

    def ground(self, dream_text: str, fragments: list[Any]) -> list[Any]:  # noqa: ARG002
        self.call_count += 1
        self.last_fragments = fragments
        # Return fragments with verified=True added
        return [{**f, "verified": True} for f in fragments]


def _make_mock_session() -> MagicMock:
    session = MagicMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    execute_result = MagicMock()
    execute_result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=execute_result)
    return session


# ---------------------------------------------------------------------------
# AC-1: Pipeline order — ImageryExtractor → MotifInductor → MotifGrounder
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_calls_in_order() -> None:
    """Stubs are called in the correct order: extract → induce → ground."""
    call_order: list[str] = []

    class _OrderExtractor:
        async def extract(self, dream_text: str) -> list[ImageryFragment]:  # noqa: ARG002
            call_order.append("extract")
            return _make_fragments()

    class _OrderInductor:
        async def induce(self, fragments: list[ImageryFragment]) -> list[MotifCandidate]:  # noqa: ARG002
            call_order.append("induce")
            return _make_candidates()

    class _OrderGrounder:
        def ground(self, dream_text: str, fragments: list[Any]) -> list[Any]:  # noqa: ARG002
            call_order.append("ground")
            return [{**f, "verified": True} for f in fragments]

    service = MotifService(
        imagery_extractor=_OrderExtractor(),  # type: ignore[arg-type]
        motif_inductor=_OrderInductor(),  # type: ignore[arg-type]
        motif_grounder=_OrderGrounder(),  # type: ignore[arg-type]
    )
    session = _make_mock_session()
    dream_entry = _make_dream_entry()

    await service.run(dream_entry, session)

    assert call_order == ["extract", "induce", "ground"], (
        f"Expected extract → induce → ground, got {call_order}"
    )


# ---------------------------------------------------------------------------
# AC-2: Rows written with status='draft' and correct model_version
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_motif_induction_rows_have_draft_status_and_model_version() -> None:
    fragments = _make_fragments()
    candidates = _make_candidates()
    service = MotifService(
        imagery_extractor=_StubImageryExtractor(fragments),
        motif_inductor=_StubMotifInductor(candidates),
        motif_grounder=_StubMotifGrounder(),
    )
    session = _make_mock_session()
    dream_entry = _make_dream_entry()

    await service.run(dream_entry, session)

    assert session.add.call_count == 1
    row = session.add.call_args[0][0]
    assert row.status == "draft"
    assert row.model_version == _MODEL_VERSION
    session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_one_row_per_motif_candidate() -> None:
    """One MotifInduction row must be persisted per candidate returned."""
    fragments = _make_fragments()
    candidates = [
        MotifCandidate(
            label="label-a",
            rationale="rationale a",
            confidence="high",
            imagery_indices=[0],
        ),
        MotifCandidate(
            label="label-b",
            rationale="rationale b",
            confidence="low",
            imagery_indices=[1],
        ),
    ]
    service = MotifService(
        imagery_extractor=_StubImageryExtractor(fragments),
        motif_inductor=_StubMotifInductor(candidates),
        motif_grounder=_StubMotifGrounder(),
    )
    session = _make_mock_session()
    dream_entry = _make_dream_entry()

    await service.run(dream_entry, session)

    assert session.add.call_count == 2


@pytest.mark.asyncio
async def test_row_has_correct_label_rationale_confidence() -> None:
    fragments = _make_fragments()
    candidates = _make_candidates()
    service = MotifService(
        imagery_extractor=_StubImageryExtractor(fragments),
        motif_inductor=_StubMotifInductor(candidates),
        motif_grounder=_StubMotifGrounder(),
    )
    session = _make_mock_session()
    dream_entry = _make_dream_entry()

    await service.run(dream_entry, session)

    row = session.add.call_args[0][0]
    assert row.label == "obstructed vertical movement"
    assert row.rationale == "Stairs and locked door both impede upward progress."
    assert row.confidence == "high"


@pytest.mark.asyncio
async def test_row_dream_id_matches_entry() -> None:
    fragments = _make_fragments()
    candidates = _make_candidates()
    service = MotifService(
        imagery_extractor=_StubImageryExtractor(fragments),
        motif_inductor=_StubMotifInductor(candidates),
        motif_grounder=_StubMotifGrounder(),
    )
    session = _make_mock_session()
    dream_entry = _make_dream_entry()

    await service.run(dream_entry, session)

    row = session.add.call_args[0][0]
    assert row.dream_id == dream_entry.id


@pytest.mark.asyncio
async def test_fragments_field_contains_grounded_fragments() -> None:
    """The fragments JSONB field must store the verified fragments list."""
    fragments = _make_fragments()
    candidates = _make_candidates()
    grounder = _StubMotifGrounder()
    service = MotifService(
        imagery_extractor=_StubImageryExtractor(fragments),
        motif_inductor=_StubMotifInductor(candidates),
        motif_grounder=grounder,
    )
    session = _make_mock_session()
    dream_entry = _make_dream_entry()

    await service.run(dream_entry, session)

    row = session.add.call_args[0][0]
    # All fragments in the row must have 'verified' key
    for frag in row.fragments:
        assert "verified" in frag


# ---------------------------------------------------------------------------
# AC-5: MotifService does NOT write to dream_themes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_does_not_import_or_write_dream_themes() -> None:
    """MotifService must not add any DreamTheme objects to the session."""
    import app.services.motif_service as ms_module

    # Confirm DreamTheme is not imported in the service module
    assert not hasattr(ms_module, "DreamTheme"), "motif_service must not import DreamTheme"

    from app.models.theme import DreamTheme

    fragments = _make_fragments()
    candidates = _make_candidates()
    service = MotifService(
        imagery_extractor=_StubImageryExtractor(fragments),
        motif_inductor=_StubMotifInductor(candidates),
        motif_grounder=_StubMotifGrounder(),
    )
    session = _make_mock_session()
    dream_entry = _make_dream_entry()

    await service.run(dream_entry, session)

    for c in session.add.call_args_list:
        obj = c[0][0]
        assert not isinstance(obj, DreamTheme), "MotifService must not write DreamTheme rows"


# ---------------------------------------------------------------------------
# Failure handling: ImageryExtractor fails → no crash, no DB write
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_imagery_extractor_failure_does_not_crash() -> None:
    service = MotifService(
        imagery_extractor=_StubImageryExtractor(
            [], raise_exc=ImageryExtractionError("LLM unavailable")
        ),
        motif_inductor=_StubMotifInductor([]),
        motif_grounder=_StubMotifGrounder(),
    )
    session = _make_mock_session()
    dream_entry = _make_dream_entry()

    # Must not raise
    await service.run(dream_entry, session)

    session.add.assert_not_called()
    session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_motif_inductor_failure_does_not_crash() -> None:
    fragments = _make_fragments()
    service = MotifService(
        imagery_extractor=_StubImageryExtractor(fragments),
        motif_inductor=_StubMotifInductor([], raise_exc=MotifInductionError("LLM error")),
        motif_grounder=_StubMotifGrounder(),
    )
    session = _make_mock_session()
    dream_entry = _make_dream_entry()

    # Must not raise
    await service.run(dream_entry, session)

    session.add.assert_not_called()
    session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_empty_fragments_result_in_no_db_write() -> None:
    """If ImageryExtractor returns an empty list, no rows are written."""
    service = MotifService(
        imagery_extractor=_StubImageryExtractor([]),
        motif_inductor=_StubMotifInductor([]),
        motif_grounder=_StubMotifGrounder(),
    )
    session = _make_mock_session()
    dream_entry = _make_dream_entry()

    await service.run(dream_entry, session)

    session.add.assert_not_called()
    session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_empty_candidates_result_in_no_db_write() -> None:
    """If MotifInductor returns an empty list, no rows are written."""
    service = MotifService(
        imagery_extractor=_StubImageryExtractor(_make_fragments()),
        motif_inductor=_StubMotifInductor([]),
        motif_grounder=_StubMotifGrounder(),
    )
    session = _make_mock_session()
    dream_entry = _make_dream_entry()

    await service.run(dream_entry, session)

    session.add.assert_not_called()
    session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_run_returns_early_when_motif_inductions_already_exist() -> None:
    existing_row_result = MagicMock()
    existing_row_result.scalar_one_or_none.return_value = uuid.uuid4()

    session = _make_mock_session()
    session.execute = AsyncMock(return_value=existing_row_result)

    imagery_extractor = _StubImageryExtractor(_make_fragments())
    service = MotifService(
        imagery_extractor=imagery_extractor,
        motif_inductor=_StubMotifInductor(_make_candidates()),
        motif_grounder=_StubMotifGrounder(),
    )

    await service.run(_make_dream_entry(), session)

    assert imagery_extractor.call_count == 0
    session.add.assert_not_called()
    session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_run_skips_pipeline_when_rows_already_exist() -> None:
    existing_row_result = MagicMock()
    existing_row_result.scalar_one_or_none.return_value = uuid.uuid4()

    session = _make_mock_session()
    session.execute = AsyncMock(return_value=existing_row_result)

    imagery_extractor = AsyncMock()
    service = MotifService(
        imagery_extractor=SimpleNamespace(extract=imagery_extractor),
        motif_inductor=_StubMotifInductor(_make_candidates()),
        motif_grounder=_StubMotifGrounder(),
    )

    await service.run(_make_dream_entry(), session)

    imagery_extractor.assert_not_awaited()
    session.add.assert_not_called()
    session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_run_does_not_commit_caller_provided_session_on_success() -> None:
    service = MotifService(
        imagery_extractor=_StubImageryExtractor(_make_fragments()),
        motif_inductor=_StubMotifInductor(_make_candidates()),
        motif_grounder=_StubMotifGrounder(),
    )
    session = _make_mock_session()

    await service.run(_make_dream_entry(), session)

    session.commit.assert_not_called()


# ---------------------------------------------------------------------------
# AC-3 / AC-4: Feature flag behaviour in ingest pipeline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingest_calls_motif_service_when_flag_is_true() -> None:
    """When MOTIF_INDUCTION_ENABLED=true, MotifService.run is called."""
    from app.workers import ingest as ingest_module

    motif_service_mock = MagicMock()
    motif_service_mock.run = AsyncMock()

    dream_entry = _make_dream_entry()
    session_mock = MagicMock()
    session_mock.__aenter__ = AsyncMock(return_value=session_mock)
    session_mock.__aexit__ = AsyncMock(return_value=False)
    session_mock.get = AsyncMock(return_value=dream_entry)
    session_mock.commit = AsyncMock()

    session_factory = MagicMock(return_value=session_mock)

    target = ingest_module.PipelineTarget(
        dream_id=dream_entry.id,
        needs_analysis=False,
        needs_indexing=False,
    )

    with patch.object(ingest_module, "get_settings") as mock_settings:
        settings = MagicMock()
        settings.MOTIF_INDUCTION_ENABLED = True
        mock_settings.return_value = settings

        await ingest_module._run_post_store_pipeline(
            ctx={},
            session_factory=session_factory,
            analysis_service=MagicMock(),
            motif_service=motif_service_mock,
            pipeline_targets=[target],
        )

    motif_service_mock.run.assert_called_once()
    session_mock.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_ingest_skips_motif_service_when_flag_is_false() -> None:
    """When MOTIF_INDUCTION_ENABLED=false, MotifService.run is never called."""
    from app.workers import ingest as ingest_module

    motif_service_mock = MagicMock()
    motif_service_mock.run = AsyncMock()

    dream_entry = _make_dream_entry()
    target = ingest_module.PipelineTarget(
        dream_id=dream_entry.id,
        needs_analysis=False,
        needs_indexing=False,
    )

    with patch.object(ingest_module, "get_settings") as mock_settings:
        settings = MagicMock()
        settings.MOTIF_INDUCTION_ENABLED = False
        mock_settings.return_value = settings

        await ingest_module._run_post_store_pipeline(
            ctx={},
            session_factory=MagicMock(),
            analysis_service=MagicMock(),
            motif_service=motif_service_mock,
            pipeline_targets=[target],
        )

    motif_service_mock.run.assert_not_called()


@pytest.mark.asyncio
async def test_ingest_commits_after_motif_service_run_returns() -> None:
    from app.workers import ingest as ingest_module

    call_order: list[str] = []

    async def _run(_: Any, session: Any) -> None:
        call_order.append("run")

    motif_service_mock = MagicMock()
    motif_service_mock.run = AsyncMock(side_effect=_run)

    dream_entry = _make_dream_entry()
    session_mock = MagicMock()
    session_mock.__aenter__ = AsyncMock(return_value=session_mock)
    session_mock.__aexit__ = AsyncMock(return_value=False)
    session_mock.get = AsyncMock(return_value=dream_entry)

    async def _commit() -> None:
        call_order.append("commit")

    session_mock.commit = AsyncMock(side_effect=_commit)
    session_factory = MagicMock(return_value=session_mock)

    target = ingest_module.PipelineTarget(
        dream_id=dream_entry.id,
        needs_analysis=False,
        needs_indexing=False,
    )

    with patch.object(ingest_module, "get_settings") as mock_settings:
        settings = MagicMock()
        settings.MOTIF_INDUCTION_ENABLED = True
        mock_settings.return_value = settings

        await ingest_module._run_post_store_pipeline(
            ctx={},
            session_factory=session_factory,
            analysis_service=MagicMock(),
            motif_service=motif_service_mock,
            pipeline_targets=[target],
        )

    assert call_order == ["run", "commit"]

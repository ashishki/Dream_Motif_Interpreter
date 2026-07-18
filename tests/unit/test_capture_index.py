from __future__ import annotations

from functools import partial
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.services.capture_index import index_capture_best_effort


@pytest.mark.asyncio
async def test_capture_index_returns_zero_instead_of_propagating_provider_outage() -> None:
    dream_id = uuid4()
    session_factory = object()
    facade_index_callable = partial(
        index_capture_best_effort,
        session_factory=session_factory,
    )

    with patch(
        "app.services.capture_index.index_dream",
        AsyncMock(side_effect=RuntimeError("provider unavailable")),
    ) as index_dream:
        result = await facade_index_callable(dream_id)

    assert result == 0
    index_dream.assert_awaited_once_with(
        {"session_factory": session_factory},
        dream_id=dream_id,
    )

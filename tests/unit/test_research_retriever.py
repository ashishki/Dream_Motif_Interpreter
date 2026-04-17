from __future__ import annotations

import json
import time

import pytest

from app.research.retriever import ResearchAPIError, ResearchRetriever


class StubResponse:
    def __init__(self, payload: dict, *, should_fail: bool = False) -> None:
        self.text = json.dumps(payload)
        self._should_fail = should_fail

    def raise_for_status(self) -> None:
        if self._should_fail:
            raise RuntimeError("boom")


class StubHTTPClient:
    def __init__(
        self,
        payload: dict | None = None,
        *,
        should_fail: bool = False,
        sleep_seconds: float = 0.0,
    ) -> None:
        self.payload = payload or {"results": []}
        self.should_fail = should_fail
        self.sleep_seconds = sleep_seconds
        self.calls: list[tuple[str, dict, float]] = []

    def post(self, url: str, *, json: dict, timeout: float) -> StubResponse:
        self.calls.append((url, json, timeout))
        if self.sleep_seconds:
            time.sleep(self.sleep_seconds)
        return StubResponse(self.payload, should_fail=self.should_fail)


@pytest.mark.asyncio
async def test_retrieve_returns_at_most_five_results() -> None:
    client = StubHTTPClient(
        payload={
            "results": [
                {"url": f"https://example.com/{idx}", "content": f"excerpt {idx}"}
                for idx in range(7)
            ]
        }
    )
    retriever = ResearchRetriever("https://api.tavily.com", "test-key", http_client=client)

    results = await retriever.retrieve("crossing water")

    assert len(results) == 5
    assert results[0].keys() == {"url", "excerpt", "retrieved_at"}
    assert client.calls[0][0] == "https://api.tavily.com/search"
    assert client.calls[0][1]["max_results"] == 5


@pytest.mark.asyncio
async def test_retrieve_raises_research_api_error_on_http_failure() -> None:
    retriever = ResearchRetriever(
        "https://api.tavily.com",
        "test-key",
        http_client=StubHTTPClient(should_fail=True),
    )

    with pytest.raises(ResearchAPIError):
        await retriever.retrieve("flooded basement")


@pytest.mark.asyncio
async def test_retrieve_enforces_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.research.retriever.REQUEST_TIMEOUT_SECONDS", 0.01)
    retriever = ResearchRetriever(
        "https://api.tavily.com",
        "test-key",
        http_client=StubHTTPClient(sleep_seconds=0.05),
    )

    with pytest.raises(ResearchAPIError, match="timed out"):
        await retriever.retrieve("labyrinth")

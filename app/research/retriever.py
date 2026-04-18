from __future__ import annotations

import asyncio
import contextvars
import json
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any
from urllib import error as urllib_error
from urllib import request

from app.shared.tracing import get_meter, get_tracer


REQUEST_TIMEOUT_SECONDS = 5.0
MAX_RESULTS = 5


class ResearchAPIError(Exception):
    """Raised when the external research API request fails."""


class ResearchRetriever:
    def __init__(self, base_url: str, api_key: str, http_client: Any | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._http_client = http_client
        self._tracer = get_tracer(__name__)
        self._meter = get_meter(__name__)
        self._retrieve_counter = self._meter.create_counter(
            "research.retrieve_total",
            description="Research API calls",
        )

    async def retrieve(self, query_label: str) -> list[dict[str, str]]:
        with self._tracer.start_as_current_span("research_retriever.retrieve") as span:
            span.set_attribute("component", "research_retriever")
            payload = {
                "api_key": self._api_key,
                "query": query_label,
                "max_results": MAX_RESULTS,
            }
            context = contextvars.copy_context()

            try:
                try:
                    raw_response = await asyncio.wait_for(
                        asyncio.to_thread(
                            context.run,
                            self._send_request,
                            payload,
                        ),
                        timeout=REQUEST_TIMEOUT_SECONDS,
                    )
                except asyncio.TimeoutError as exc:
                    raise ResearchAPIError("Research API request timed out") from exc
                except (urllib_error.HTTPError, urllib_error.URLError) as exc:
                    raise ResearchAPIError("Research API request failed") from exc
                except Exception as exc:
                    if isinstance(exc, ResearchAPIError):
                        raise
                    raise ResearchAPIError("Research API request failed") from exc

                payload_json = json.loads(raw_response)
                raw_results = payload_json.get("results", [])
                if not isinstance(raw_results, list):
                    raise ResearchAPIError("Research API response did not include a results list")

                retrieved_at = datetime.now(timezone.utc).isoformat()
                results: list[dict[str, str]] = []
                for item in raw_results[:MAX_RESULTS]:
                    if not isinstance(item, Mapping):
                        continue

                    url = str(item.get("url", "")).strip()
                    if not url:
                        continue

                    excerpt = str(
                        item.get("content") or item.get("raw_content") or item.get("snippet") or ""
                    ).strip()
                    results.append(
                        {
                            "url": url,
                            "excerpt": excerpt,
                            "retrieved_at": retrieved_at,
                        }
                    )

                self._retrieve_counter.add(1, {"status": "success"})
                return results
            except ResearchAPIError:
                self._retrieve_counter.add(1, {"status": "failure"})
                raise

    def _send_request(self, payload: dict[str, Any]) -> str:
        if self._http_client is not None:
            response = self._http_client.post(
                f"{self._base_url}/search",
                json=payload,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            raise_for_status = getattr(response, "raise_for_status", None)
            if callable(raise_for_status):
                raise_for_status()
            text = getattr(response, "text", None)
            if text is not None:
                return str(text)
            json_method = getattr(response, "json", None)
            if callable(json_method):
                return json.dumps(json_method())
            raise ResearchAPIError("Injected HTTP client returned an unsupported response")

        request_payload = json.dumps(payload).encode("utf-8")
        http_request = request.Request(
            f"{self._base_url}/search",
            data=request_payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(http_request, timeout=REQUEST_TIMEOUT_SECONDS) as response:  # noqa: S310
            return response.read().decode("utf-8")

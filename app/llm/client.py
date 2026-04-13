from __future__ import annotations

from typing import Any

from app.shared.config import get_settings
from app.shared.tracing import get_tracer


class LLMClientError(RuntimeError):
    """Raised when the Anthropic client cannot be initialized or returns no text."""


class AnthropicLLMClient:
    def __init__(self, *, model: str = "claude-haiku-4-5") -> None:
        self._model = model
        self._client: Any | None = None

    async def complete(self, system: str, user: str) -> str:
        tracer = get_tracer(__name__)

        with tracer.start_as_current_span("llm.complete"):
            client = self._get_client()
            with tracer.start_as_current_span("anthropic.messages.create"):
                response = await client.messages.create(
                    model=self._model,
                    max_tokens=1000,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                )

            content = getattr(response, "content", [])
            text_blocks = [
                block.text
                for block in content
                if getattr(block, "type", None) == "text" and getattr(block, "text", None)
            ]
            if not text_blocks:
                raise LLMClientError("Anthropic response did not contain text content")

            return "\n".join(text_blocks).strip()

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client

        try:
            from anthropic import AsyncAnthropic
        except ImportError as exc:
            raise LLMClientError("anthropic package is required to use AnthropicLLMClient") from exc

        settings = get_settings()
        self._client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        return self._client

from functools import lru_cache

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult

_tracer_provider: TracerProvider | None = None


class _NoOpSpanExporter(SpanExporter):
    def export(self, spans: object) -> SpanExportResult:
        return SpanExportResult.SUCCESS


def _get_provider() -> TracerProvider:
    global _tracer_provider
    if _tracer_provider is None:
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(_NoOpSpanExporter()))
        trace.set_tracer_provider(provider)
        _tracer_provider = provider
    return _tracer_provider


@lru_cache(maxsize=None)
def get_tracer(name: str = "dream_motif_interpreter") -> trace.Tracer:
    """Return the shared tracer. All code that creates spans must import from here."""
    provider = _get_provider()
    return provider.get_tracer(name)

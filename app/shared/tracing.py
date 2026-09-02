from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Any

import structlog
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.metrics import Meter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.shared.config import get_settings

SERVICE_NAME = "dream-motif-interpreter"


@lru_cache(maxsize=1)
def _get_provider() -> TracerProvider:
    provider = TracerProvider()
    if _otlp_enabled():
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    return provider


@lru_cache(maxsize=None)
def get_tracer(name: str = SERVICE_NAME) -> trace.Tracer:
    """Return the shared tracer. All code that creates spans must import from here."""
    return _get_provider().get_tracer(name)


@lru_cache(maxsize=1)
def _get_meter_provider() -> MeterProvider:
    readers = [PeriodicExportingMetricReader(OTLPMetricExporter())] if _otlp_enabled() else []
    provider = MeterProvider(metric_readers=readers)
    metrics.set_meter_provider(provider)
    return provider


def _otlp_enabled() -> bool:
    """Export telemetry only when an OTLP endpoint is explicitly configured."""
    return bool(os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip())


@lru_cache(maxsize=None)
def get_meter(name: str = SERVICE_NAME) -> Meter:
    """Return the shared meter. All code that creates metrics must import from here."""
    return _get_meter_provider().get_meter(name)


def _add_service_fields(
    _logger: Any,
    _method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    settings = get_settings()
    event_dict.setdefault("env", settings.ENV)
    event_dict.setdefault("service", SERVICE_NAME)
    return event_dict


def _add_trace_fields(
    _logger: Any,
    _method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    span = trace.get_current_span()
    span_context = span.get_span_context()
    if not span_context.is_valid:
        event_dict.setdefault("trace_id", None)
        event_dict.setdefault("span_id", None)
        return event_dict

    event_dict.setdefault("trace_id", f"{span_context.trace_id:032x}")
    event_dict.setdefault("span_id", f"{span_context.span_id:016x}")
    return event_dict


def _redact_pii(
    _logger: Any,
    _method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    event_dict.pop("raw_text", None)
    event_dict.pop("chunk_text", None)
    event_dict.pop("justification", None)
    return event_dict


def configure_logging() -> None:
    if getattr(configure_logging, "_configured", False):
        return

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            _add_service_fields,
            _add_trace_fields,
            _redact_pii,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        cache_logger_on_first_use=True,
    )
    configure_logging._configured = True


def get_logger(name: str) -> Any:
    configure_logging()
    return structlog.get_logger(name)

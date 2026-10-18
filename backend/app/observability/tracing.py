# app/observability/tracing.py
import contextlib
from typing import Any, Dict, Optional
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import Status, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

# Initialize global TracerProvider if not already set
_provider = trace.get_tracer_provider()
if not isinstance(_provider, TracerProvider):
    _provider = TracerProvider()
    _memory_exporter = InMemorySpanExporter()
    _provider.add_span_processor(SimpleSpanProcessor(_memory_exporter))
    trace.set_tracer_provider(_provider)

_tracer = trace.get_tracer("gympro.ai", "1.0.0")
_propagator = TraceContextTextMapPropagator()


def get_tracer(name: str = "gympro.ai"):
    """Returns the configured OpenTelemetry tracer."""
    return trace.get_tracer(name, "1.0.0")


def get_current_trace_id() -> Optional[str]:
    """Returns the hex string of the current active trace ID, or None."""
    span = trace.get_current_span()
    if span and span.get_span_context().is_valid:
        return f"{span.get_span_context().trace_id:032x}"
    return None


def get_current_span_id() -> Optional[str]:
    """Returns the hex string of the current active span ID, or None."""
    span = trace.get_current_span()
    if span and span.get_span_context().is_valid:
        return f"{span.get_span_context().span_id:016x}"
    return None


def inject_trace_headers(carrier: Dict[str, Any]) -> Dict[str, Any]:
    """Injects current W3C tracecontext and GymPro x-trace-id into headers dictionary."""
    _propagator.inject(carrier)
    current_trace = get_current_trace_id()
    if current_trace:
        carrier["x-trace-id"] = current_trace
    return carrier


def extract_trace_headers(carrier: Dict[str, Any]):
    """Extracts W3C tracecontext from carrier dictionary."""
    return _propagator.extract(carrier)


@contextlib.contextmanager
def trace_span(
    name: str,
    attributes: Optional[Dict[str, Any]] = None,
    kind: trace.SpanKind = trace.SpanKind.INTERNAL,
):
    """
    Context manager that starts an OpenTelemetry span, sets initial attributes,
    records exceptions if raised, and closes cleanly.
    """
    with _tracer.start_as_current_span(name, kind=kind) as span:
        if attributes:
            for k, v in attributes.items():
                if v is not None:
                    # OTel attributes accept bool, int, float, str, or sequences
                    if isinstance(v, (bool, int, float, str)):
                        span.set_attribute(k, v)
                    else:
                        span.set_attribute(k, str(v))
        try:
            yield span
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise

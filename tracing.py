"""
Shared OpenTelemetry setup used by both the `gateway` and `worker` services.

Each service gets its own TracerProvider (resource-tagged with its
service.name) and exports finished spans as JSON Lines to its own file
under traces/, e.g. traces/gateway.jsonl / traces/worker.jsonl.

We use a SimpleSpanProcessor (synchronous, exports on every span.end())
rather than the default BatchSpanProcessor so spans hit disk immediately.
That matters for the demo: a short-lived request/response cycle (or a
subprocess killed right after the test assertions) must not lose spans
sitting in an unflushed batch buffer.

No collector, no Jaeger, no OTLP network exporter -- just plain JSON on
disk, which merge_traces.py and viewer/index.html know how to read.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Sequence

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.sdk.trace import TracerProvider, ReadableSpan
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult

PROJECT_ROOT = Path(__file__).resolve().parent
TRACES_DIR = PROJECT_ROOT / "traces"


def _hex_trace_id(trace_id: int) -> str:
    return format(trace_id, "032x")


def _hex_span_id(span_id: int) -> str:
    return format(span_id, "016x")


class JsonLinesFileSpanExporter(SpanExporter):
    """Appends one JSON object per finished span to a .jsonl file.

    The record shape is a deliberately simplified stand-in for
    OTLP/JSON: it keeps exactly what the merge/viewer tools need
    (trace_id, span_id, parent_span_id, timing, name, service, kind,
    status, attributes) without pulling in the full OTLP protobuf/JSON
    schema.
    """

    def __init__(self, file_path: Path):
        self._file_path = file_path
        self._lock = threading.Lock()
        self._file_path.parent.mkdir(parents=True, exist_ok=True)

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        try:
            with self._lock:
                with open(self._file_path, "a", encoding="utf-8") as f:
                    for span in spans:
                        f.write(json.dumps(self._span_to_dict(span)) + "\n")
                    f.flush()
                    os.fsync(f.fileno())
            return SpanExportResult.SUCCESS
        except Exception:
            return SpanExportResult.FAILURE

    @staticmethod
    def _span_to_dict(span: ReadableSpan) -> dict:
        ctx = span.get_span_context()
        parent_span_id = None
        if span.parent is not None:
            parent_span_id = _hex_span_id(span.parent.span_id)

        resource_attrs = dict(span.resource.attributes) if span.resource else {}

        return {
            "name": span.name,
            "trace_id": _hex_trace_id(ctx.trace_id),
            "span_id": _hex_span_id(ctx.span_id),
            "parent_span_id": parent_span_id,
            "kind": span.kind.name if span.kind else None,
            "start_time_unix_nano": span.start_time,
            "end_time_unix_nano": span.end_time,
            "duration_ms": round((span.end_time - span.start_time) / 1_000_000, 3)
            if span.start_time and span.end_time
            else None,
            "status": {
                "status_code": span.status.status_code.name if span.status else None,
                "description": span.status.description if span.status else None,
            },
            "attributes": dict(span.attributes) if span.attributes else {},
            "service_name": resource_attrs.get(SERVICE_NAME),
        }

    def shutdown(self) -> None:  # pragma: no cover - nothing to clean up
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:  # pragma: no cover
        return True


def setup_tracing(service_name: str, traces_dir: Path = TRACES_DIR) -> TracerProvider:
    """Create and globally register a TracerProvider for `service_name`.

    Idempotent-ish: if a real (non-proxy) TracerProvider is already set,
    it is returned as-is so re-importing this module (e.g. in tests)
    doesn't clobber an already-configured provider.
    """
    existing = trace.get_tracer_provider()
    if isinstance(existing, TracerProvider):
        return existing

    resource = Resource.create({SERVICE_NAME: service_name})
    provider = TracerProvider(resource=resource)

    jsonl_path = traces_dir / f"{service_name}.jsonl"
    exporter = JsonLinesFileSpanExporter(jsonl_path)
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    trace.set_tracer_provider(provider)
    return provider


def reset_trace_file(service_name: str, traces_dir: Path = TRACES_DIR) -> None:
    """Truncate a service's trace file. Handy for tests/demos that want
    a clean slate before firing a request."""
    path = traces_dir / f"{service_name}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("")

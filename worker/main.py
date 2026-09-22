"""
`worker` service (port 8001).

Receives a unit of work from the `gateway` service over real HTTP,
does some fake work (sleep + a bit of CPU busywork), creates a
manually-instrumented child span simulating a database query, and
returns a result.

opentelemetry-instrumentation-fastapi wraps the ASGI app so every
incoming HTTP request automatically:
  1. extracts the W3C `traceparent` header (if present) from the
     inbound request via the global propagator, and
  2. starts a server span whose parent is that extracted context.

That's the whole trick behind cross-service propagation: the gateway's
outbound httpx call carries `traceparent`, and this app's instrumentation
picks it up instead of starting a brand-new trace.
"""
from __future__ import annotations

import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tracing import setup_tracing  # noqa: E402

SERVICE_NAME = "worker"
setup_tracing(SERVICE_NAME)  # must run before FastAPI app / instrumentation is created

from fastapi import FastAPI  # noqa: E402
from opentelemetry import trace  # noqa: E402
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor  # noqa: E402
from pydantic import BaseModel  # noqa: E402

tracer = trace.get_tracer(SERVICE_NAME)

app = FastAPI(title="worker")
FastAPIInstrumentor.instrument_app(app)


class WorkRequest(BaseModel):
    order_id: str
    item_count: int = 1


class WorkResponse(BaseModel):
    order_id: str
    rows_written: int
    processing_ms: float


def _simulate_db_query(order_id: str, item_count: int) -> int:
    """Manually-created child span simulating a database write.

    This is the "internal manually-created child span" required by the
    project: it is not produced by any auto-instrumentation, it's a
    plain `tracer.start_as_current_span` call nested under the server
    span that FastAPIInstrumentor already started for this request.
    """
    with tracer.start_as_current_span("db.query.insert_order") as span:
        span.set_attribute("db.system", "postgresql")
        span.set_attribute("db.statement", "INSERT INTO orders (id, items) VALUES ($1, $2)")
        span.set_attribute("db.order_id", order_id)
        # fake DB latency, proportional to how much "work" was requested
        time.sleep(0.01 + 0.005 * item_count)
        rows = item_count
        span.set_attribute("db.rows_affected", rows)
        return rows


def _simulate_cpu_work(item_count: int) -> None:
    with tracer.start_as_current_span("compute.checksum") as span:
        span.set_attribute("compute.item_count", item_count)
        total = 0
        for i in range(200_000 * max(item_count, 1)):
            total += i * i % 97
        span.set_attribute("compute.result", total)


@app.post("/work", response_model=WorkResponse)
def do_work(req: WorkRequest) -> WorkResponse:
    start = time.perf_counter()

    # a little unrelated sleep, e.g. "waiting on a lock"
    time.sleep(0.02 + random.random() * 0.01)

    _simulate_cpu_work(req.item_count)
    rows = _simulate_db_query(req.order_id, req.item_count)

    elapsed_ms = (time.perf_counter() - start) * 1000
    return WorkResponse(order_id=req.order_id, rows_written=rows, processing_ms=elapsed_ms)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": SERVICE_NAME}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8001, log_level="info")

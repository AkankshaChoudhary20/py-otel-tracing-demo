"""
`gateway` service (port 8000).

Exposes POST /checkout. On every request it makes a *real* outbound
HTTP call (via httpx) to the `worker` service's POST /work endpoint.

opentelemetry-instrumentation-httpx wraps the httpx client so every
outgoing request automatically:
  1. starts a CLIENT span for the call, and
  2. injects the current trace context into the outgoing request's
     `traceparent` header via the global propagator (W3C Trace Context
     by default).

Combined with the worker's FastAPIInstrumentor (which extracts that
header on the way in), both services' spans end up sharing one
trace_id, with the worker's server span parented directly under this
service's outbound CLIENT span -- real network-crossing propagation,
not two independently-generated traces that happen to match.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tracing import setup_tracing  # noqa: E402

SERVICE_NAME = "gateway"
setup_tracing(SERVICE_NAME)  # must run before FastAPI app / instrumentation is created

import httpx  # noqa: E402
from fastapi import FastAPI, HTTPException  # noqa: E402
from opentelemetry import trace  # noqa: E402
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor  # noqa: E402
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor  # noqa: E402
from pydantic import BaseModel  # noqa: E402

tracer = trace.get_tracer(SERVICE_NAME)

WORKER_BASE_URL = "http://127.0.0.1:8001"

app = FastAPI(title="gateway")
FastAPIInstrumentor.instrument_app(app)
# Instruments httpx.Client / httpx.AsyncClient globally: every request made
# through them gets a CLIENT span + a `traceparent` header injected.
HTTPXClientInstrumentor().instrument()


class CheckoutRequest(BaseModel):
    item_count: int = 1


class CheckoutResponse(BaseModel):
    order_id: str
    rows_written: int
    worker_processing_ms: float
    trace_id: str


@app.post("/checkout", response_model=CheckoutResponse)
def checkout(req: CheckoutRequest) -> CheckoutResponse:
    order_id = str(uuid.uuid4())

    with tracer.start_as_current_span("checkout.handle_order") as span:
        span.set_attribute("order.id", order_id)
        span.set_attribute("order.item_count", req.item_count)
        # echo the trace_id back to the caller -- handy for humans (and
        # for the test suite) to grab the exact trace to look up later,
        # e.g. via `python merge_traces.py <trace_id>`.
        trace_id_hex = format(span.get_span_context().trace_id, "032x")

        with httpx.Client(timeout=10.0) as client:
            try:
                resp = client.post(
                    f"{WORKER_BASE_URL}/work",
                    json={"order_id": order_id, "item_count": req.item_count},
                )
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                span.record_exception(exc)
                raise HTTPException(status_code=502, detail=f"worker call failed: {exc}") from exc

        data = resp.json()

    return CheckoutResponse(
        order_id=order_id,
        rows_written=data["rows_written"],
        trace_id=trace_id_hex,
        worker_processing_ms=data["processing_ms"],
    )


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": SERVICE_NAME}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")

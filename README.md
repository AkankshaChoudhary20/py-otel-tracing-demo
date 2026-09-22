# py-otel-tracing-demo

A small, fully self-contained distributed tracing demo. Two independent
FastAPI services talk to each other over real HTTP, both instrumented with
the real OpenTelemetry Python SDK, and the point of the project is to prove
— with an automated test, not just eyeballing logs — that **W3C
trace-context propagation actually works across the network hop**: both
services' spans end up in the *same trace*, with the callee's root span
correctly parented under the caller's outbound HTTP span.

No Jaeger, no OpenTelemetry Collector, no external services of any kind are
required. Spans are exported as JSON Lines straight to disk, and a
zero-dependency HTML file renders them as a waterfall/Gantt chart.

## Architecture

```
        POST /checkout                POST /work
 client ───────────────▶ gateway ───────────────▶ worker
                         :8000                     :8001
                            │                          │
                    traces/gateway.jsonl      traces/worker.jsonl
```

- **`gateway`** (`gateway/main.py`, port 8000) — exposes `POST /checkout`.
  On every request it makes a real outbound HTTP call, via an
  `httpx.Client`, to the `worker` service's `POST /work`.
- **`worker`** (`worker/main.py`, port 8001) — exposes `POST /work`. It does
  fake work: a short `time.sleep`, a manually-created child span
  `compute.checksum` (busy CPU loop), and a manually-created child span
  `db.query.insert_order` that simulates a database write (with
  `db.system`, `db.statement`, `db.rows_affected` attributes) — then
  returns a result.
- **`tracing.py`** — shared setup used by both services. Each service gets
  its own `TracerProvider`, tagged with its `service.name` via an OTel
  `Resource`, and a `SimpleSpanProcessor` that synchronously exports every
  finished span as one JSON line to that service's own file
  (`traces/gateway.jsonl`, `traces/worker.jsonl`). `SimpleSpanProcessor` is
  used (rather than the default batching processor) specifically so spans
  hit disk immediately — important for a short-lived demo request or a
  subprocess that gets torn down right after a test assertion.
- **`merge_traces.py`** — reads both `.jsonl` files, filters to one
  `trace_id` (defaults to the most recent one seen), sorts by start time,
  and writes a single merged JSON array.
- **`viewer/index.html`** — one self-contained HTML+JS file (no build step,
  no CDN, no charting library) that loads a merged trace JSON (via a file
  picker or paste box) and renders it as an SVG waterfall: one row per
  span, x-axis = time, bars colored by service, hover for full span
  details (ids, timestamps, attributes). It also ships with a "Load
  bundled example trace" button backed by an inlined copy of
  `traces/example_merged_trace.json`, so you can see it work without
  running anything first.
- **`tests/test_propagation.py`** — see "What the test proves" below.

## How W3C trace-context propagation works here

Both services call `opentelemetry.instrumentation.fastapi.FastAPIInstrumentor.instrument_app(app)`,
which wraps the ASGI app so every incoming request:

1. runs the globally-registered propagator (W3C Trace Context by default)
   over the inbound headers, looking for `traceparent` (and optionally
   `tracestate`);
2. if found, starts the request's SERVER span as a **child of that
   extracted context** instead of starting a brand new trace.

The gateway additionally calls `HTTPXClientInstrumentor().instrument()`,
which wraps `httpx.Client`/`AsyncClient` so every outgoing request:

1. starts a CLIENT span for the call, as a child of whatever span is
   currently active (here: `checkout.handle_order`);
2. runs the same propagator **in inject mode**, writing a `traceparent`
   header (format `00-<trace_id>-<span_id>-<flags>`) onto the outgoing
   request, encoding *that CLIENT span's* trace_id and span_id.

So the chain is: `gateway`'s `checkout.handle_order` span → `gateway`'s
outbound `httpx` CLIENT span → **`traceparent` header on the wire** →
`worker`'s inbound `POST /work` SERVER span. The only thing connecting the
two processes' independent OpenTelemetry SDK instances is that literal HTTP
header — there is no shared memory, no shared exporter, nothing else tying
the two traces together. That's what makes the propagation "real" rather
than emulated.

## Running the services

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# terminal 1
python -m uvicorn worker.main:app --host 127.0.0.1 --port 8001

# terminal 2
python -m uvicorn gateway.main:app --host 127.0.0.1 --port 8000

# terminal 3 — fire a request
curl -s -X POST http://127.0.0.1:8000/checkout \
  -H 'Content-Type: application/json' \
  -d '{"item_count": 2}' | python3 -m json.tool
```

Example response (the gateway echoes back the `trace_id` for convenience):

```json
{
    "order_id": "f9294790-8fdb-443b-b738-2e06779383dd",
    "rows_written": 2,
    "worker_processing_ms": 72.08787499985192,
    "trace_id": "ad82afd73c6a40ab21de102943a57476"
}
```

Each service appends real spans to its own file as it handles requests. A
real example span, exactly as written by `tracing.py`'s
`JsonLinesFileSpanExporter` to `traces/worker.jsonl` (the worker's inbound
server span for that same request):

```json
{
  "name": "POST /work",
  "trace_id": "ad82afd73c6a40ab21de102943a57476",
  "span_id": "3615c1b6a123a8c1",
  "parent_span_id": "8d7c24ce300af66a",
  "kind": "SERVER",
  "start_time_unix_nano": 1790055078913026000,
  "end_time_unix_nano": 1790055078986340000,
  "duration_ms": 73.314,
  "status": { "status_code": "UNSET", "description": null },
  "attributes": {
    "http.scheme": "http",
    "http.host": "127.0.0.1:8001",
    "http.target": "/work",
    "http.url": "http://127.0.0.1:8001/work",
    "http.method": "POST",
    "http.route": "/work",
    "http.status_code": 200
  },
  "service_name": "worker"
}
```

`parent_span_id: "8d7c24ce300af66a"` is not a coincidence — it is exactly
the `span_id` of the gateway's outbound `httpx` CLIENT span for the same
request, found in `traces/gateway.jsonl`:

```json
{
  "name": "POST",
  "trace_id": "ad82afd73c6a40ab21de102943a57476",
  "span_id": "8d7c24ce300af66a",
  "parent_span_id": "e3db07e3190045c1",
  "kind": "CLIENT",
  "start_time_unix_nano": 1790055078912345000,
  "end_time_unix_nano": 1790055078986784000,
  "duration_ms": 74.439,
  "attributes": {
    "http.method": "POST",
    "http.url": "http://127.0.0.1:8001/work",
    "http.status_code": 200
  },
  "service_name": "gateway"
}
```

Both records also share `trace_id: "ad82afd73c6a40ab21de102943a57476"` —
the full chain (gateway server span → `checkout.handle_order` → gateway
CLIENT span → **network** → worker SERVER span → worker's `compute.checksum`
/ `db.query.insert_order` child spans) is one connected trace.

## Viewing a trace

```bash
python merge_traces.py ad82afd73c6a40ab21de102943a57476 -o mytrace.json
# or, to just grab whatever trace was most recently recorded:
python merge_traces.py -o mytrace.json
# list all trace_ids currently on disk:
python merge_traces.py --list
```

Then open `viewer/index.html` directly in a browser (double-click it, or
`open viewer/index.html` on macOS) and load `mytrace.json` via the file
picker. Or just click **"Load bundled example trace"** to see the waterfall
for the example checkout captured in `traces/example_merged_trace.json`
without running anything.

The waterfall shows one row per span (indented by parent/child nesting),
positioned and sized by its real start time and duration, colored by
service (blue = gateway, orange = worker); hovering a bar shows the full
span record (ids, timestamps, attributes) in a tooltip.

## What the pytest test proves

`tests/test_propagation.py` deliberately does **not** use two in-process
`fastapi.testclient.TestClient` instances calling each other directly —
that would prove nothing about real network propagation, since two
TestClients share the same Python process and could "cheat" via shared
state. Instead it:

1. Launches `gateway` and `worker` as two **separate OS subprocesses**,
   each running its own real `uvicorn` server on its own port — the only
   thing connecting them is a real HTTP client, just like production.
2. Fires one real HTTP request at the gateway (`POST /checkout`).
3. Reads back what each service actually wrote to its own
   `traces/*.jsonl` file (scoped to the exact `trace_id` the gateway
   echoed back in its response, since concurrent health-check polling
   also generates its own, unrelated traces against both services).
4. Asserts, non-tautologically:
   - both services recorded spans for this request;
   - every span found (from both files) shares the same `trace_id`;
   - the worker's inbound `SERVER` span's `parent_span_id` **equals** the
     `span_id` of the gateway's outbound `httpx` `CLIENT` span — i.e. real
     cross-process parent/child linkage carried by the `traceparent`
     header, not merely "same trace_id by luck";
   - the worker's manually-created `db.query.insert_order` child span is
     itself correctly parented under the worker's own server span;
   - the gateway's own `checkout.handle_order` span is the parent of its
     outbound CLIENT span (full chain sanity check).

Actual run:

```
$ pytest tests/ -v
============================= test session starts ==============================
platform darwin -- Python 3.14.2, pytest-9.1.1, pluggy-1.6.0
collected 1 item

tests/test_propagation.py::test_checkout_propagates_trace_context_across_services PASSED [100%]

============================== 1 passed in 0.92s ===============================
```

## Project layout

```
py-otel-tracing-demo/
├── gateway/main.py          # FastAPI app, port 8000, POST /checkout
├── worker/main.py           # FastAPI app, port 8001, POST /work
├── tracing.py               # shared TracerProvider + JSONL file exporter
├── merge_traces.py          # merges/filters traces/*.jsonl -> one JSON array
├── viewer/index.html        # self-contained SVG waterfall viewer
├── tests/test_propagation.py
├── traces/
│   ├── example_merged_trace.json   # committed: powers the viewer's demo button
│   ├── gateway.jsonl                # generated at runtime, gitignored
│   └── worker.jsonl                 # generated at runtime, gitignored
└── requirements.txt
```

## Notes on trace file handling

`traces/*.jsonl` (the raw, per-service, ever-growing span logs) are
gitignored since they're regenerated every time you run the services or
the test suite. `traces/example_merged_trace.json` is the one deliberate
exception: it's a small, static, already-merged example (produced once via
`merge_traces.py` from a real local run) that's committed so the viewer has
something to show out of the box.

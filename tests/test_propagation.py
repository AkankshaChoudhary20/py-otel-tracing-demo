"""
Automated proof of cross-service trace-context propagation.

This launches `gateway` and `worker` as real, separate OS processes
(each running its own uvicorn/FastAPI app on its own port), fires one
real HTTP request through the gateway's /checkout endpoint -- which in
turn makes a real HTTP call to the worker's /work endpoint -- and then
reads back what each service actually exported to its own
traces/*.jsonl file.

Subprocess + real HTTP (rather than two FastAPI TestClient instances)
is used deliberately: TestClient calls happen in-process and would not
exercise a genuine network hop or prove that the W3C `traceparent`
header is what's doing the propagation work. Here, the only channel
connecting the two processes' OpenTelemetry SDK instances is the
literal HTTP header on the wire.

What's asserted (not tautological):
  1. Both services actually recorded spans.
  2. Every span from both services shares the same trace_id.
  3. The worker's inbound SERVER span's parent_span_id equals the
     span_id of the gateway's outbound httpx CLIENT span -- i.e. real
     parent/child linkage carried across the network boundary, not
     merely "same trace_id by coincidence".
  4. The worker's manually-created "db.query.insert_order" child span
     is itself correctly parented under the worker's own server span,
     and shares the same trace_id too.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TRACES_DIR = PROJECT_ROOT / "traces"
GATEWAY_URL = "http://127.0.0.1:8000"
WORKER_URL = "http://127.0.0.1:8001"


def _wait_for_health(url: str, timeout: float = 15.0) -> None:
    deadline = time.time() + timeout
    last_exc = None
    while time.time() < deadline:
        try:
            resp = httpx.get(f"{url}/health", timeout=1.0)
            if resp.status_code == 200:
                return
        except httpx.HTTPError as exc:
            last_exc = exc
        time.sleep(0.2)
    raise RuntimeError(f"service at {url} did not become healthy in time: {last_exc}")


def _start_service(module: str, port: int, log_path: Path) -> subprocess.Popen:
    log_file = open(log_path, "w", encoding="utf-8")
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            module,
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=str(PROJECT_ROOT),
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )
    return proc


@pytest.fixture(scope="module")
def running_services():
    TRACES_DIR.mkdir(exist_ok=True)
    (TRACES_DIR / "gateway.jsonl").write_text("")
    (TRACES_DIR / "worker.jsonl").write_text("")

    worker_proc = _start_service("worker.main:app", 8001, TRACES_DIR / "worker.server.log")
    gateway_proc = _start_service("gateway.main:app", 8000, TRACES_DIR / "gateway.server.log")

    try:
        _wait_for_health(WORKER_URL)
        _wait_for_health(GATEWAY_URL)
        yield
    finally:
        for proc in (gateway_proc, worker_proc):
            proc.terminate()
        for proc in (gateway_proc, worker_proc):
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    spans = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                spans.append(json.loads(line))
    return spans


def _wait_for_spans(path: Path, min_count: int, timeout: float = 5.0) -> list[dict]:
    deadline = time.time() + timeout
    spans: list[dict] = []
    while time.time() < deadline:
        spans = _read_jsonl(path)
        if len(spans) >= min_count:
            return spans
        time.sleep(0.1)
    return spans


def test_checkout_propagates_trace_context_across_services(running_services):
    # --- fire one real request through the gateway ---
    # (the health-check polling above this fixture also generates its own,
    # unrelated traces against both services, so we must not assume the
    # trace files contain *only* our request's spans -- we scope everything
    # below to the exact trace_id the gateway echoes back for THIS request)
    resp = httpx.post(f"{GATEWAY_URL}/checkout", json={"item_count": 3}, timeout=10.0)
    assert resp.status_code == 200
    body = resp.json()
    assert body["rows_written"] == 3
    shared_trace_id = body["trace_id"]
    assert len(shared_trace_id) == 32  # 128-bit trace id, hex

    # --- read back what each service actually exported, scoped to this trace ---
    def spans_for_trace(path: Path, min_count: int) -> list[dict]:
        deadline = time.time() + 5.0
        while time.time() < deadline:
            matching = [s for s in _read_jsonl(path) if s["trace_id"] == shared_trace_id]
            if len(matching) >= min_count:
                return matching
            time.sleep(0.1)
        return matching

    gateway_spans = spans_for_trace(TRACES_DIR / "gateway.jsonl", min_count=2)
    worker_spans = spans_for_trace(TRACES_DIR / "worker.jsonl", min_count=3)

    assert len(gateway_spans) >= 2, f"expected gateway spans, got {gateway_spans}"
    assert len(worker_spans) >= 3, f"expected worker spans, got {worker_spans}"

    # 1. every span found this way already shares the trace_id by
    #    construction (we filtered on it) -- but assert none of them are
    #    somehow *also* missing/blank, and that both services indeed
    #    contributed spans to the SAME trace_id rather than the filter
    #    just returning nothing for one side.
    all_trace_ids = {s["trace_id"] for s in gateway_spans} | {s["trace_id"] for s in worker_spans}
    assert all_trace_ids == {shared_trace_id}

    # 2. find the gateway's outbound httpx CLIENT span (the one that
    #    physically carried the traceparent header to the worker)
    gateway_client_spans = [s for s in gateway_spans if s["kind"] == "CLIENT"]
    assert len(gateway_client_spans) == 1, f"expected exactly one CLIENT span, got {gateway_client_spans}"
    gateway_client_span = gateway_client_spans[0]

    # 3. find the worker's inbound SERVER span (root span of the worker process
    #    for this request)
    worker_server_spans = [s for s in worker_spans if s["kind"] == "SERVER"]
    assert len(worker_server_spans) == 1, f"expected exactly one SERVER span, got {worker_server_spans}"
    worker_server_span = worker_server_spans[0]

    # *** THE actual propagation proof ***
    # The worker's root span's parent must be the gateway's CLIENT span --
    # linked purely via the traceparent header that crossed the network.
    assert worker_server_span["parent_span_id"] == gateway_client_span["span_id"], (
        "worker's server span is not parented under the gateway's outbound "
        f"client span: worker.parent_span_id={worker_server_span['parent_span_id']!r} "
        f"vs gateway.client.span_id={gateway_client_span['span_id']!r}"
    )
    # sanity: it's definitely not parented under nothing, and not
    # coincidentally equal to its own span_id
    assert worker_server_span["parent_span_id"] is not None
    assert worker_server_span["parent_span_id"] != worker_server_span["span_id"]

    # 4. the manually-created "db query" child span is correctly nested
    #    under the worker's own server span
    db_spans = [s for s in worker_spans if s["name"] == "db.query.insert_order"]
    assert len(db_spans) == 1, f"expected the manual db child span, got {db_spans}"
    db_span = db_spans[0]
    assert db_span["parent_span_id"] == worker_server_span["span_id"]
    assert db_span["trace_id"] == shared_trace_id

    # 5. the gateway's own internal "checkout.handle_order" span is the
    #    parent of the outbound CLIENT span (full chain sanity check)
    handle_order_spans = [s for s in gateway_spans if s["name"] == "checkout.handle_order"]
    assert len(handle_order_spans) == 1
    assert gateway_client_span["parent_span_id"] == handle_order_spans[0]["span_id"]

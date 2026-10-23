#!/usr/bin/env python3
"""
Merge the per-service JSON Lines trace files (traces/gateway.jsonl,
traces/worker.jsonl) into one JSON array of spans for a single
trace_id, suitable for loading into viewer/index.html.

Usage:
    python merge_traces.py                     # merge the most recent trace_id
    python merge_traces.py <trace_id>           # merge a specific trace_id
    python merge_traces.py <trace_id> -o out.json
    python merge_traces.py --list                # list known trace_ids

By default it reads traces/gateway.jsonl and traces/worker.jsonl next
to this script and writes the merged array to stdout.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parent
TRACES_DIR = PROJECT_ROOT / "traces"
DEFAULT_FILES = [TRACES_DIR / "gateway.jsonl", TRACES_DIR / "worker.jsonl"]


def read_spans(paths: Iterable[Path]) -> list[dict]:
    spans = []
    for path in paths:
        if not path.exists():
            continue
        with open(path, "r", encoding="utf-8") as f:
            for line_number, raw_line in enumerate(f, 1):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    span = json.loads(line)
                    if not isinstance(span, dict):
                        raise ValueError(f"Span must be a JSON object at {path}:{line_number}")
                    spans.append(span)
                except json.JSONDecodeError as error:
                    if not raw_line.endswith('\n'):
                        # Exporters may still be writing the final JSONL record.
                        continue
                    raise ValueError(f"Invalid span JSON at {path}:{line_number}") from error
    return spans


def most_recent_trace_id(spans: list[dict]) -> str | None:
    if not spans:
        return None
    latest = max(spans, key=lambda s: s.get("start_time_unix_nano") or 0)
    return latest.get("trace_id")


def merge(trace_id: str | None, paths: Iterable[Path]) -> list[dict]:
    spans = read_spans(paths)
    if trace_id is None:
        trace_id = most_recent_trace_id(spans)
    if trace_id is None:
        return []
    matching = [s for s in spans if s.get("trace_id") == trace_id]
    matching.sort(key=lambda s: s.get("start_time_unix_nano") or 0)
    return matching


def list_trace_ids(paths: Iterable[Path]) -> list[str]:
    spans = read_spans(paths)
    seen: dict[str, None] = {}
    for s in sorted(spans, key=lambda s: s.get("start_time_unix_nano") or 0):
        seen.setdefault(s.get("trace_id"), None)
    return list(seen.keys())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("trace_id", nargs="?", default=None, help="trace_id to filter by (default: most recent)")
    parser.add_argument("-o", "--output", default=None, help="output file (default: stdout)")
    parser.add_argument(
        "--files",
        nargs="+",
        default=None,
        help="jsonl files to read (default: traces/gateway.jsonl traces/worker.jsonl)",
    )
    parser.add_argument("--list", action="store_true", help="list known trace_ids and exit")
    args = parser.parse_args()

    paths = [Path(p) for p in args.files] if args.files else DEFAULT_FILES

    try:
        if args.list:
            for tid in list_trace_ids(paths):
                print(tid)
            return

        merged = merge(args.trace_id, paths)
    except (ValueError, OSError) as error:
        parser.error(str(error))

    if not merged:
        print("No matching spans found.", file=sys.stderr)
        sys.exit(1)

    output_json = json.dumps(merged, indent=2)
    if args.output:
        Path(args.output).write_text(output_json)
        print(f"Wrote {len(merged)} spans to {args.output}", file=sys.stderr)
    else:
        print(output_json)


if __name__ == "__main__":
    main()

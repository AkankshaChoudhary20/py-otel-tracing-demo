import json
from merge_traces import merge, list_trace_ids

def test_untagged_latest_span_does_not_hide_valid_trace(tmp_path):
    path = tmp_path / 'spans.jsonl'
    spans = [{'trace_id': 'valid', 'start_time_unix_nano': 1},
             {'start_time_unix_nano': 2}, {'trace_id': '', 'start_time_unix_nano': 3}]
    path.write_text(''.join(json.dumps(s) + '\n' for s in spans))
    assert merge(None, [path]) == [spans[0]]
    assert list_trace_ids([path]) == ['valid']

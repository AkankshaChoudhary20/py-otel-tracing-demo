import json
import pytest
from merge_traces import merge

@pytest.mark.parametrize('end', [-1, True, 'later', 1.5, 9])
def test_invalid_span_end_has_source_location(tmp_path, end):
    path = tmp_path / 'spans.jsonl'
    path.write_text(json.dumps({'trace_id': 'trace', 'start_time_unix_nano': 10, 'end_time_unix_nano': end}) + '\n')
    with pytest.raises(ValueError, match=r'spans.jsonl:1'):
        merge(None, [path])

def test_zero_duration_and_missing_end_remain_valid(tmp_path):
    path = tmp_path / 'spans.jsonl'
    spans = [{'trace_id': 'trace', 'start_time_unix_nano': 10, 'end_time_unix_nano': 10}, {'trace_id': 'trace', 'start_time_unix_nano': 11}]
    path.write_text(''.join(json.dumps(s) + '\n' for s in spans))
    assert merge(None, [path]) == spans

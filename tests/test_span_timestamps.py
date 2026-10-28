import json
import pytest
from merge_traces import merge


@pytest.mark.parametrize('timestamp', ['yesterday', True, -1, 1.5])
def test_invalid_timestamps_have_actionable_errors(tmp_path, timestamp):
    path = tmp_path / 'spans.jsonl'
    spans = [{'trace_id': 'ok', 'start_time_unix_nano': 1},
             {'trace_id': 'bad', 'start_time_unix_nano': timestamp}]
    path.write_text(''.join(json.dumps(s) + '\n' for s in spans))
    with pytest.raises(ValueError, match=r'spans.jsonl:2'):
        merge(None, [path])


def test_absent_timestamp_remains_supported(tmp_path):
    path = tmp_path / 'spans.jsonl'
    path.write_text('{"trace_id":"ok"}\n')
    assert merge(None, [path]) == [{'trace_id': 'ok'}]

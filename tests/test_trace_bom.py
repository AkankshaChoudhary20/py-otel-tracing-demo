import json
from merge_traces import merge, list_trace_ids

def test_bom_prefixed_trace_file_preserves_all_records(tmp_path):
    path = tmp_path / 'trace.jsonl'
    spans = [{'trace_id': 'one', 'start_time_unix_nano': 1}, {'trace_id': 'one', 'start_time_unix_nano': 2}]
    path.write_text('\n'.join(map(json.dumps, spans)) + '\n', encoding='utf-8-sig')
    assert merge(None, [path]) == spans
    assert list_trace_ids([path]) == ['one']

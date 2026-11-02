import pytest
from merge_traces import read_spans

@pytest.mark.parametrize('value', ['NaN', 'Infinity', '-Infinity', '1e999'])
def test_nonfinite_nested_span_attributes_are_rejected(tmp_path, value):
    p = tmp_path / 'trace.jsonl'
    p.write_text('{"trace_id":"a","attributes":{"duration":' + value + '}}\n')
    with pytest.raises(ValueError, match='trace.jsonl:1'):
        read_spans([p])

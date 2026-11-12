import subprocess
import sys
from pathlib import Path

def test_unwritable_output_is_a_cli_error(tmp_path):
    spans = tmp_path / 'spans.jsonl'
    spans.write_text('{"trace_id":"trace","start_time_unix_nano":1}\n')
    result = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / 'merge_traces.py'), 'trace', '--files', str(spans), '-o', str(tmp_path / 'missing' / 'out.json')], capture_output=True, text=True)
    assert result.returncode == 2
    assert 'error:' in result.stderr
    assert 'Traceback' not in result.stderr

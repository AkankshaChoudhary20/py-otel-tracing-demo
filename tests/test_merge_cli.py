import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class MergeCliTests(unittest.TestCase):
    def test_malformed_input_returns_clean_error_for_merge_and_list(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bad.jsonl'
            path.write_text('invalid\n')
            for flags in ([], ['--list']):
                result = subprocess.run([sys.executable, 'merge_traces.py', *flags, '--files', str(path)], capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('bad.jsonl:1', result.stderr)
                self.assertNotIn('Traceback', result.stderr)

    def test_valid_merge_keeps_json_stdout(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'ok.jsonl'
            span = {'trace_id': 'abc', 'start_time_unix_nano': 1}
            path.write_text(json.dumps(span) + '\n')
            result = subprocess.run([sys.executable, 'merge_traces.py', '--files', str(path)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), [span])

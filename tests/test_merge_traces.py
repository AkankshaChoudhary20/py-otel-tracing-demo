import json
import tempfile
import unittest
from pathlib import Path

from merge_traces import merge, read_spans


class MergeTests(unittest.TestCase):
    def test_partial_final_record_does_not_hide_completed_spans(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "spans.jsonl"
            span = {"trace_id": "complete", "start_time_unix_nano": 1}
            path.write_text(json.dumps(span) + '\n{"trace_id": "incomplete')
            self.assertEqual(merge(None, [path]), [span])

    def test_complete_record_without_newline_is_kept(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "spans.jsonl"
            span = {"trace_id": "complete", "start_time_unix_nano": 1}
            path.write_text(json.dumps(span))
            self.assertEqual(read_spans([path]), [span])

    def test_malformed_completed_record_reports_location(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "spans.jsonl"
            path.write_text('{}\ninvalid\n')
            with self.assertRaisesRegex(ValueError, 'spans.jsonl:2'):
                read_spans([path])


if __name__ == '__main__':
    unittest.main()

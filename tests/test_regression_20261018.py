import json
import tempfile
import unittest
from pathlib import Path
from merge_traces import read_spans

class SpanShapeTests(unittest.TestCase):
    def test_nonobject_records_report_file_and_line(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'spans.jsonl'
            for value in [None, [], 1, 'span', True]:
                path.write_text('{}\n' + json.dumps(value) + '\n')
                with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'spans.jsonl:2'):
                    read_spans([path])

    def test_object_records_are_kept(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'spans.jsonl'
            path.write_text('{"trace_id": "a"}\n')
            self.assertEqual(read_spans([path]), [{'trace_id': 'a'}])

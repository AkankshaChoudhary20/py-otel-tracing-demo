import tempfile
import unittest
from pathlib import Path
from merge_traces import read_spans

class DuplicateSpanFieldsTests(unittest.TestCase):
    def test_duplicate_fields_are_reported_with_source_location(self):
        for record in ('{"trace_id":"a","trace_id":"b"}', '{"start_time_unix_nano":9,"start_time_unix_nano":1}', '{"attributes":{"route":"a","route":"b"}}'):
            with self.subTest(record=record), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'trace.jsonl'
                path.write_text(record + '\n')
                with self.assertRaisesRegex(ValueError, r'trace.jsonl:1'):
                    read_spans([path])

    def test_normal_attributes_and_partial_tail_still_work(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'trace.jsonl'
            path.write_text('{"trace_id":"a","attributes":{"route":"a"}}\n{"trace_id":')
            self.assertEqual(read_spans([path]), [{'trace_id': 'a', 'attributes': {'route': 'a'}}])
